from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Awaitable

from backend.agents.concept_agent import ConceptAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.resume_agent import ResumeAgent
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension
from backend.models.llm_router import LLMRouter, MODEL_TIERS
from backend.services.orchestrator import Orchestrator


MODELS = [
    "anthropic/claude-haiku-4.5",
    "google/gemini-3.1-flash-lite",
]

APPARAO_RESUME = """S V S APPARAO
Education: IIIT Sri City, B.Tech CSE, CGPA 7.51/10.
Product Analyst, Daily Mantra, AppsforBharat, Dec 2024-Present.
- Increased user retention from 25% to 42% through A/B testing and deployment features (Video, Today, AI Guruji).
- Optimized trial-to-subscription conversion rate from 27% to 42% by reducing trial period from 7 days to 1 day.
- Increased Mantra Track End completion from 27.5% to 55.5% by launching Videos and Today experiments.
- Architected analytics event tracking for Daily Mantra zero-to-one product, defining session flow, engagement, feature adoption, and conversion funnel events.
Associate Business Analyst, AppsforBharat, May 2024-Nov 2024.
- Automated AppsFlyer dashboards for campaign/ad-set CAC, CPI, CPM, spend.
Computer Vision Intern, IIT Hyderabad.
- Benchmarked blob tracking, YOLO with SORT, and optical flow across 400+ road frames.
"""

MESSY_ENGINEER_RESUME = """Name: K. contact blah.
stuff: built ai things frontend/backend cv maybe.
Experience --
AI Engineer Intern @ PixelForge: created prompt workflow for image edits; reduced failed regeneration; had seed control and mask checks; React/Node UI.
ML Project: tiny audio classifier on microcontroller, TensorFlow Lite Micro int8, <10ms target, 95 percent-ish validation.
Research helper: OCR + retrieval notes for scanned forms, some benchmarking, not sure exact metrics.
Skills: python javascript sql react fastapi pytorch opencv lots of APIs.
"""

TRAP_RESUME = """Aarav M
Product Analyst, Northstar Commerce.
- Improved checkout conversion from 41% to 36% after fixing instrumentation for payment-start, payment-fail, retry-success, and order-confirmed.
- Discount experiment showed +12% conversion lift but 4.6 point gross-margin drop.
Product Analyst, VideoHealth.
- Reported 75% retention improvement while denominator changed from lesson_started to video_started.
- Built dashboards for Video Growth, AI Coach Quality, and Today Engagement with different active-user definitions.
"""


CASES = [
    {
        "name": "apparao_clean_product",
        "target_role": "Product Analyst",
        "years_experience": "1",
        "resume": APPARAO_RESUME,
        "answer": (
            "I defined Daily Mantra events for session start, mantra discovery, track start, track end, "
            "video exposure, trial start, payment initiated, and subscription success so retention and conversion experiments had clean denominators."
        ),
        "partial": "I defined event taxonomy for trial conversion and mantra track completion",
        "expected_concepts": ["event", "taxonomy", "trial", "conversion"],
        "anchor_expected": True,
        "application_answer": (
            "For BNPL I would separate payment initiated, authorization pending, webhook success, failed authorization, "
            "and order confirmed. I would use pending states in daily reporting and keep refund and support-ticket guardrails."
        ),
    },
    {
        "name": "messy_engineer",
        "target_role": "AI Agent Development Engineer",
        "years_experience": "1",
        "resume": MESSY_ENGINEER_RESUME,
        "answer": (
            "For the image workflow I preserved seed consistency and mask validation through a React and Node interface, "
            "then tested whether prompt edits changed only the intended region instead of regenerating the whole image."
        ),
        "partial": "seed control mask validation prompt workflow React Node image edits",
        "expected_concepts": ["seed", "mask", "prompt", "react"],
        "anchor_expected": True,
        "application_answer": (
            "On a noisy wearable I would test microphone drift, confidence thresholds, buffering, and an uncertain-class path instead of forcing every clip into a label."
        ),
    },
    {
        "name": "vague_overclaim",
        "target_role": "Product Analyst",
        "years_experience": "3",
        "resume": TRAP_RESUME,
        "answer": (
            "We looked at dashboards and conversion improved because of campaigns and models. I do not remember the exact denominator or guardrails."
        ),
        "partial": "dashboards conversion improved models campaigns denominator not remember",
        "expected_concepts": ["dashboard", "conversion", "denominator"],
        "anchor_expected": False,
        "application_answer": (
            "I would use AI dashboards for buyers and sellers. The main metric would be growth, and I would check details later."
        ),
    },
    {
        "name": "terse_honest_gap",
        "target_role": "Product Analyst",
        "years_experience": "2",
        "resume": TRAP_RESUME,
        "answer": (
            "I owned some event definitions and queries, but another engineer productionized the dbt models, so my ownership should be scoped."
        ),
        "partial": "owned event definitions queries engineer productionized dbt ownership scoped",
        "expected_concepts": ["event", "queries", "dbt", "ownership"],
        "anchor_expected": True,
        "application_answer": (
            "I would first define what I own: event names, firing rules, denominator checks, and handoff notes for the engineer."
        ),
    },
]


@contextmanager
def small_model(model: str):
    old = MODEL_TIERS.get("small")
    MODEL_TIERS["small"] = model
    try:
        yield
    finally:
        MODEL_TIERS["small"] = old


def _question_score(value: object, *, require_question_mark: bool = True) -> tuple[int, list[str]]:
    text = ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, dict):
        text = str(value.get("question") or value.get("followup") or "").strip()
    failures: list[str] = []
    if len(text.split()) < 6:
        failures.append("too_short")
    if len(text.split()) > 45:
        failures.append("too_long")
    question_like_openers = (
        "walk me through",
        "tell me",
        "explain",
        "describe",
        "help me understand",
        "show me",
    )
    if require_question_mark and "?" not in text and not text.lower().startswith(question_like_openers):
        failures.append("not_a_question")
    generic = {"tell me more", "walk me through that", "can you elaborate"}
    if any(phrase in text.lower() for phrase in generic):
        failures.append("generic_question")
    return max(0, 100 - 25 * len(failures)), failures


def _concept_score(result: object, expected: list[str]) -> tuple[int, list[str]]:
    failures: list[str] = []
    if not isinstance(result, list):
        return 0, ["non_list"]
    joined = " ".join(str(x).lower() for x in result)
    hits = sum(1 for term in expected if term in joined)
    if hits < max(2, len(expected) - 1):
        failures.append(f"low_expected_hits:{hits}/{len(expected)}")
    if len(result) > 14:
        failures.append("too_many_concepts")
    return max(0, round((hits / max(len(expected), 1)) * 100) - 10 * len(failures)), failures


def _resume_score(result: object, case: dict[str, str]) -> tuple[int, list[str]]:
    failures: list[str] = []
    if not isinstance(result, dict):
        return 0, ["non_dict"]
    for key in ("skills", "tools", "projects", "claims", "experiences"):
        if key not in result:
            failures.append(f"missing_{key}")
    claims = result.get("claims") if isinstance(result.get("claims"), list) else []
    projects = result.get("projects") if isinstance(result.get("projects"), list) else []
    haystack = json.dumps({"claims": claims, "projects": projects}, ensure_ascii=True).lower()
    role = case["target_role"].lower()
    if "product" in role and not any(term in haystack for term in ("retention", "conversion", "dashboard", "instrument")):
        failures.append("missed_product_claims")
    if "engineer" in role and not any(term in haystack for term in ("prompt", "seed", "mask", "tiny", "audio")):
        failures.append("missed_engineer_claims")
    if "@" in haystack or "contact" in haystack:
        failures.append("contact_noise_leaked")
    if len(claims) < 2 and len(projects) < 1:
        failures.append("too_few_claims_projects")
    return max(0, 100 - 20 * len(failures)), failures


def _speculative_score(result: object) -> tuple[int, list[str]]:
    failures: list[str] = []
    if not isinstance(result, dict):
        return 0, ["non_dict"]
    action = result.get("action")
    if action not in {"keep", "replace", "use_map_candidate"}:
        failures.append("bad_action")
    if action == "replace":
        q_score, q_failures = _question_score(result.get("question"))
        failures.extend(f"question_{f}" for f in q_failures)
        return max(0, min(100, q_score - 10 * len(failures))), failures
    return max(0, 100 - 25 * len(failures)), failures


def _anchor_score(result: object, *, expected: bool) -> tuple[int, list[str]]:
    text = str(result or "").strip()
    failures: list[str] = []
    if not expected:
        if not text or text.lower() in {"none", "empty string", '""', "null"}:
            return 100, []
        if len(text.split()) < 8:
            return 85, []
        return 50, ["invented_anchor_for_vague_answer"]
    if len(text.split()) < 8:
        failures.append("too_short")
    if text.lower() in {"none", "empty string", '""'}:
        failures.append("empty")
    if not any(term in text.lower() for term in ("built", "defined", "workflow", "event", "seed", "mask", "query", "taxonomy")):
        failures.append("not_implementation_specific")
    return max(0, 100 - 25 * len(failures)), failures


def _coverage_score(result: object, expected_ids: set[str]) -> tuple[int, list[str]]:
    failures: list[str] = []
    if not isinstance(result, dict):
        return 0, ["non_dict"]
    if not result:
        failures.append("empty")
    if not expected_ids.intersection(result.keys()):
        failures.append("no_expected_dimension_ids")
    bad_states = [v for v in result.values() if v not in {"voluntary", "recovered_deep", "recovered_surface", "missed", "incorrect", "not_evaluated"}]
    if bad_states:
        failures.append("bad_states")
    return max(0, 100 - 30 * len(failures)), failures


async def timed(task: str, model: str, case: str, coro: Awaitable[Any], timeout: float = 45.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return {
            "task": task,
            "model": model,
            "case": case,
            "ok": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "result": result.to_dict() if hasattr(result, "to_dict") else result,
            "error": "",
        }
    except Exception as exc:
        return {
            "task": task,
            "model": model,
            "case": case,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "result": None,
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


def coverage_map_for(case: dict[str, str]) -> dict:
    dims = [
        CoverageDimension(
            id="denominator",
            label="Denominator discipline",
            description="Defines what enters the metric denominator",
            expected_approaches=["event boundary", "entry criteria"],
            surfacing_question="What exactly enters the denominator in this scenario?",
            weight=2.5,
        ),
        CoverageDimension(
            id="guardrails",
            label="Guardrails",
            description="Names adverse metrics to protect",
            expected_approaches=["refunds", "support tickets", "retention"],
            surfacing_question="What guardrails would you watch while this ships?",
            weight=2.0,
        ),
        CoverageDimension(
            id="uncertainty",
            label="Uncertainty handling",
            description="Handles ambiguous or pending states honestly",
            expected_approaches=["pending state", "unknown bucket", "confidence threshold"],
            surfacing_question="What happens when the state is ambiguous or delayed?",
            weight=1.5,
        ),
    ]
    cmap = AnswerCoverageMap(
        application_question="Transfer this system to a new adjacent product constraint.",
        implementation_anchor=case["answer"],
        dimensions=dims,
        total_weight=sum(d.weight for d in dims),
        coverage_confidence=0.7,
    )
    return cmap.to_dict()


async def run_model_case(model: str, case: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with small_model(model):
        concept = ConceptAgent()
        concept.llm = LLMRouter(tier="small", model_override=model, timeout_override=30.0)
        row = await timed("concept_extract", model, case["name"], concept.extract(case["answer"]))
        row["score"], row["failures"] = _concept_score(row.get("result"), case["expected_concepts"]) if row["ok"] else (0, [row["error"]])
        rows.append(row)

        resume_agent = ResumeAgent()
        resume_agent.llm = LLMRouter(tier="small", model_override=model, timeout_override=60.0)
        row = await timed("resume_parse", model, case["name"], resume_agent.parse(case["resume"], case["target_role"], case["years_experience"]), 70.0)
        row["score"], row["failures"] = _resume_score(row.get("result"), case) if row["ok"] else (0, [row["error"]])
        parsed = row.get("result") if isinstance(row.get("result"), dict) else {}
        rows.append(row)

        followup = FollowUpAgent()
        followup.llm_fast = LLMRouter(tier="small", model_override=model, timeout_override=35.0)
        resume_context = _build_resume_context(parsed, case["resume"])

        row = await timed("seed_question", model, case["name"], followup.generate_seed_question(1, "curious_lead", resume_context), 45.0)
        row["score"], row["failures"] = _question_score(row.get("result")) if row["ok"] else (0, [row["error"]])
        rows.append(row)

        row = await timed(
            "clarification_fast",
            model,
            case["name"],
            followup.generate_clarification(
                "What did you personally build?",
                case["answer"],
                {"type": "ambiguous_but_promising", "weakness": "ownership scope unclear", "probe_direction": "ownership_probe"},
                "curious_lead",
                case["resume"],
                parsed_resume=parsed,
            ),
            45.0,
        )
        row["score"], row["failures"] = _question_score(row.get("result")) if row["ok"] else (0, [row["error"]])
        rows.append(row)

        row = await timed(
            "adapt_followup",
            model,
            case["name"],
            followup.adapt_followup(
                raw_followup="What was the exact mechanism that made this work?",
                question="Walk me through the strongest project.",
                answer=case["answer"],
                persona="curious_lead",
                resume_context=resume_context,
            ),
            45.0,
        )
        row["score"], row["failures"] = _question_score(row.get("result")) if row["ok"] else (0, [row["error"]])
        rows.append(row)

        row = await timed(
            "speculative_followup",
            model,
            case["name"],
            followup.generate_speculative(
                partial_text=case["partial"],
                new_entities=case["expected_concepts"][:3],
                last_question="Walk me through the strongest project.",
                persona="curious_lead",
                sprint=1,
                resume_context=resume_context,
                focus_context="Stay on the current resume claim.",
            ),
            45.0,
        )
        row["score"], row["failures"] = _speculative_score(row.get("result")) if row["ok"] else (0, [row["error"]])
        rows.append(row)

        orch = Orchestrator()
        row = await timed(
            "implementation_anchor_extract",
            model,
            case["name"],
            orch._extract_implementation_anchor("small-model-probe", case["answer"], {"target_role": case["target_role"]}),
            45.0,
        )
        row["score"], row["failures"] = _anchor_score(row.get("result"), expected=bool(case.get("anchor_expected", True))) if row["ok"] else (0, [row["error"]])
        rows.append(row)

        cmap = coverage_map_for(case)
        row = await timed(
            "coverage_dimension_eval",
            model,
            case["name"],
            orch._evaluate_coverage_dimension("denominator", cmap, case["application_answer"]),
            45.0,
        )
        if row["ok"] and isinstance(row.get("result"), tuple):
            state, _depth = row["result"]
            row["result"] = {"coverage_state": state, "recovery_depth": _depth}
            row["score"] = 100 if state in {"voluntary", "recovered_deep", "recovered_surface", "missed", "incorrect"} else 0
            row["failures"] = [] if row["score"] else ["bad_coverage_state"]
        else:
            row["score"], row["failures"] = 0, [row["error"]]
        rows.append(row)

        row = await timed(
            "application_coverage_eval",
            model,
            case["name"],
            orch._evaluate_application_coverage(cmap, case["application_answer"]),
            45.0,
        )
        row["score"], row["failures"] = _coverage_score(row.get("result"), {"denominator", "guardrails", "uncertainty"}) if row["ok"] else (0, [row["error"]])
        rows.append(row)

    return rows


def compact_result(value: object) -> object:
    if isinstance(value, str):
        return value[:400]
    if isinstance(value, dict):
        if "claims" in value or "projects" in value:
            return {
                "claims": value.get("claims", [])[:3],
                "projects": value.get("projects", [])[:3],
                "skills": value.get("skills", [])[:8],
                "tools": value.get("tools", [])[:8],
                "experience_tier": value.get("experience_tier"),
            }
        return value
    if isinstance(value, list):
        return value[:10]
    return value


def write_reports(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row["result_preview"] = compact_result(row.pop("result", None))
    out_json = Path("/tmp/antigravity_small_model_replacement.json")
    out_md = Path("/tmp/antigravity_small_model_replacement.md")
    out_json.write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding="utf-8")

    by_model: dict[str, list[dict[str, Any]]] = {}
    by_task_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
        by_task_model.setdefault((row["task"], row["model"]), []).append(row)

    lines = ["# Small Model Replacement Evaluation", ""]
    lines.append("## Model Summary")
    lines.append("| Model | Passes | Calls | Avg Score | Avg Latency ms |")
    lines.append("|---|---:|---:|---:|---:|")
    for model, items in by_model.items():
        passes = sum(1 for row in items if row["ok"] and row.get("score", 0) >= 70)
        avg_score = sum(row.get("score", 0) for row in items) / max(len(items), 1)
        avg_latency = sum(row.get("elapsed_ms", 0) for row in items) / max(len(items), 1)
        lines.append(f"| `{model}` | {passes} | {len(items)} | {avg_score:.1f} | {avg_latency:.0f} |")

    lines.extend(["", "## Task Summary"])
    lines.append("| Task | Model | Passes | Calls | Avg Score | Avg Latency ms | Failures |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for (task, model), items in sorted(by_task_model.items()):
        passes = sum(1 for row in items if row["ok"] and row.get("score", 0) >= 70)
        avg_score = sum(row.get("score", 0) for row in items) / max(len(items), 1)
        avg_latency = sum(row.get("elapsed_ms", 0) for row in items) / max(len(items), 1)
        failures = sorted({f for row in items for f in row.get("failures", []) if f})
        lines.append(f"| `{task}` | `{model}` | {passes} | {len(items)} | {avg_score:.1f} | {avg_latency:.0f} | {'; '.join(failures[:4])} |")

    lines.extend(["", f"JSON: `{out_json}`"])
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[SmallModelEval] Wrote {out_json}")
    print(f"[SmallModelEval] Wrote {out_md}")


async def main() -> None:
    models = [
        item.strip()
        for item in os.environ.get("SMALL_MODEL_CANDIDATES", ",".join(MODELS)).split(",")
        if item.strip()
    ]
    case_limit = int(os.environ.get("SMALL_MODEL_CASE_LIMIT", str(len(CASES))) or len(CASES))
    cases = CASES[:case_limit]
    repeats = int(os.environ.get("SMALL_MODEL_REPEATS", "1") or "1")
    rows: list[dict[str, Any]] = []
    for repeat in range(repeats):
        for model in models:
            print(f"[SmallModelEval] Running {model} repeat {repeat + 1}/{repeats}", flush=True)
            for case in cases:
                case_rows = await run_model_case(model, case)
                for row in case_rows:
                    row["repeat"] = repeat + 1
                rows.extend(case_rows)
    write_reports(rows)
    for model in models:
        items = [row for row in rows if row["model"] == model]
        passes = sum(1 for row in items if row["ok"] and row.get("score", 0) >= 70)
        print(f"[SmallModelEval] {model}: {passes}/{len(items)} task-cases passed")


if __name__ == "__main__":
    asyncio.run(main())
