"""
Model bake-off for Antigravity's LLM-dependent interview subtasks.

Run:
  python3 -m backend.test_model_bakeoff

The script imports backend.main so the normal application dotenv loader runs.
It does not print secrets. Results are written to /tmp.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import backend.main  # noqa: F401 - loads app environment the same way uvicorn does
from backend.agents.application_agent import ApplicationAgent
from backend.agents.discrepancy_agent import DiscrepancyAgent
from backend.agents.followup_agent import FollowUpAgent, _build_resume_context
from backend.agents.reasoning_behavior_agent import ReasoningBehaviorAgent
from backend.agents.resume_agent import ResumeAgent
from backend.agents.weakness_agent import WeaknessAgent
from backend.models.llm_router import LLMRouter, MODEL_TIERS
from backend.services import interview_map as interview_map_module
from backend.services.interview_map import generate_interview_map, validate_interview_map


MODELS = [
    {"id": "anthropic/claude-haiku-4.5", "label": "Claude Haiku 4.5"},
    {"id": "google/gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
    {"id": "google/gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
    {"id": "deepseek/deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
    {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
]

RUN_MAP = os.environ.get("BAKEOFF_RUN_MAP", "1").strip() != "0"
MAP_CASE_LIMIT = int(os.environ.get("BAKEOFF_MAP_CASE_LIMIT", "1") or "1")
CASE_LIMIT = int(os.environ.get("BAKEOFF_CASE_LIMIT", "3") or "3")


MESSY_AI_RESUME = """
(+86) 15914122353 | 123040005@link.cuhk.edu.cn| 2001 Longxiang Boulevard, Longgang District, Shenzhen :
TheChineseUniversityofHongKong,Shenzhen(B.Eng. in Computer Science and Engineering)
2024 Guangdong Government Outstanding International Student Scholarship
2025 Leading Academic Peer Advisor @ School of Data Science, CUHK-SZ
TECHNICAL SKILLS:
Top Skills: Python, C++, SQL Hybrid, RISC- V, Git, Docker, Google GCP, AWS Deployment, Linux, Deployment Testing
EXPERIENCE:
AI Agent Development Engineer [Intern] : AIGC Algorithms - Wondershare Filmora @ Shenzhen Jan 2026 – Present
Architected and prototyped an end-to-end Agent based AIGC video generation and editing pipeline on Google ADK by implementing a unified seed-based generation workflow.
Engineered a ML - feature-map control system that translates orthogonal control axes into pixel-level semantic generation instructions for Google Veo 3 seed-regeneration.
Built a semantic UI-to-latent translation interface that maps intuitive editing controls to diffusion conditioning vectors.
AI Engineer Intern : AI Model Developer - Optek Microelectronics @ Shenzhen, China 2025 July - Sept
Engineered a full-stack TinyML Audio Classification Pipeline, by integrating MediaPipe Audio for real-time feature extraction, TensorFlow Lite-Micro INT8 for quantized inference, and Edge Impulse for SDK deployment.
Optimized and delivered a custom classifier for a 700 MHz DSP + 16 MB NPU, accomplishing <10 ms latency and 4× model compression.
Research Assistant : HKU- COLUMBIA- ALIBABA- CUHKSZ@ BIRD Vision 2025 June - Sept
Reconstructed an advanced multi-modal benchmark framework that pioneered BIRD-SQL dataset.
Designed relational DB schemas, and created complex hybrid SQL queries.
"""


def _load_resume_json(path: str) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cases() -> list[dict[str, str]]:
    root = Path(__file__).resolve().parent
    loaded = [
        _load_resume_json(str(root / "runtime/qa_maps/merit_product_analyst_riya_resume.json")),
        _load_resume_json(str(root / "runtime/qa_maps/trap_product_analyst_aarav_resume.json")),
    ]
    cases: list[dict[str, str]] = []
    for item in loaded:
        if isinstance(item, dict) and item.get("resume"):
            cases.append({
                "name": str(item.get("candidate") or item.get("name") or item.get("target_role") or f"case_{len(cases)+1}"),
                "resume": str(item.get("resume") or ""),
                "target_role": str(item.get("target_role") or "Product Analyst"),
                "years_experience": str(item.get("years_experience") or "3"),
                "question": "Walk me through the strongest project or product-analysis claim on your resume.",
                "answer": (
                    "I rebuilt checkout instrumentation, separated payment-start, payment-fail, retry-success, "
                    "and order-confirmed events, then used those definitions to diagnose a funnel drop and stop a false rollout."
                ),
            })
    cases.append({
        "name": "messy_ai_engineering_resume",
        "resume": MESSY_AI_RESUME,
        "target_role": "AI Agent Development Engineer",
        "years_experience": "1",
        "question": "Walk me through the most concrete system you personally built.",
        "answer": (
            "I worked on the TinyML audio classifier and mostly handled integration of MediaPipe Audio features with "
            "TensorFlow Lite Micro INT8 deployment, but I did not own the whole model architecture."
        ),
    })
    return cases


@contextmanager
def _force_model(model_id: str):
    old_tiers = dict(MODEL_TIERS)
    old_generator = interview_map_module._MAP_GENERATOR_MODEL
    old_critic = interview_map_module._MAP_CRITIC_MODEL
    MODEL_TIERS["small"] = model_id
    MODEL_TIERS["medium"] = model_id
    MODEL_TIERS["large"] = model_id
    interview_map_module._MAP_GENERATOR_MODEL = model_id
    interview_map_module._MAP_CRITIC_MODEL = model_id
    try:
        yield
    finally:
        MODEL_TIERS.clear()
        MODEL_TIERS.update(old_tiers)
        interview_map_module._MAP_GENERATOR_MODEL = old_generator
        interview_map_module._MAP_CRITIC_MODEL = old_critic


async def _timed(label: str, coro, timeout: float = 45.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        row = {
            "task": label,
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "result": result,
        }
        print(f"[Bakeoff]   {label}: ok in {row['latency_ms']}ms", flush=True)
        return row
    except Exception as exc:
        row = {
            "task": label,
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        print(f"[Bakeoff]   {label}: FAIL {row['error_type']} in {row['latency_ms']}ms", flush=True)
        return row


def _question_score(text: str, resume: str) -> int:
    cleaned = " ".join(str(text).split())
    if not cleaned or "?" not in cleaned:
        return 0
    score = 40
    words = cleaned.split()
    if 8 <= len(words) <= 45:
        score += 15
    low = cleaned.lower()
    generic_bits = ["tell me more", "walk me through", "what did you do differently", "specific mechanism"]
    if not any(bit in low for bit in generic_bits):
        score += 10
    resume_tokens = {
        token.lower().strip(".,:;()[]")
        for token in resume.split()
        if len(token.strip(".,:;()[]")) >= 5
    }
    overlap = {token.lower().strip(".,:;()[]") for token in words} & resume_tokens
    score += min(len(overlap) * 7, 35)
    return min(score, 100)


def _resume_score(parsed: Any) -> int:
    if not isinstance(parsed, dict):
        return 0
    score = 0
    for key in ("skills", "tools", "projects", "claims", "experiences"):
        if isinstance(parsed.get(key), list) and parsed.get(key):
            score += 14
    if parsed.get("candidate_name"):
        score += 10
    if parsed.get("experience_tier") in {"junior", "mid", "senior"}:
        score += 10
    list_objects_ok = all(
        isinstance(parsed.get(key), list) and all(isinstance(item, dict) for item in parsed.get(key, []))
        for key in ("projects", "claims", "experiences")
    )
    if list_objects_ok:
        score += 10
    return min(score, 100)


def _map_score(map_payload: Any) -> int:
    if not isinstance(map_payload, dict):
        return 0
    validation = validate_interview_map(map_payload, require_all_llm=False)
    focus_areas = map_payload.get("focus_areas") or []
    score = 20 if validation.get("ready") else 0
    score += min(int(validation.get("rich_focus_count", 0) or 0) * 20, 40)
    score += min(len(focus_areas) * 8, 24)
    banned = ("scholarship", "advisor", "university", "phone", "email", "address")
    labels = " ".join(str(area.get("label", "")) for area in focus_areas).lower()
    if not any(token in labels for token in banned):
        score += 16
    return min(score, 100)


async def _run_case(model: dict[str, str], case: dict[str, str], case_index: int) -> list[dict[str, Any]]:
    model_id = model["id"]
    rows: list[dict[str, Any]] = []
    with _force_model(model_id):
        resume_agent = ResumeAgent()
        resume_agent.llm = LLMRouter(tier="small", model_override=model_id, timeout_override=35.0)
        parsed_row = await _timed(
            "resume_parse",
            resume_agent.parse(case["resume"], target_role=case["target_role"], years_experience=case["years_experience"]),
            timeout=40.0,
        )
        parsed = parsed_row.get("result") if parsed_row.get("ok") else {}
        parsed_row["score"] = _resume_score(parsed)
        rows.append(parsed_row)

        followup = FollowUpAgent()
        followup.llm = LLMRouter(tier="medium", model_override=model_id, timeout_override=35.0)
        followup.llm_fast = LLMRouter(tier="small", model_override=model_id, timeout_override=25.0)
        resume_context = _build_resume_context(parsed if isinstance(parsed, dict) else {}, case["resume"])
        seed_row = await _timed(
            "seed_question",
            followup.generate_seed_question(1, "curious_lead", resume_context),
            timeout=30.0,
        )
        seed_row["score"] = _question_score(str(seed_row.get("result", "")), case["resume"]) if seed_row.get("ok") else 0
        rows.append(seed_row)

        weakness = WeaknessAgent()
        weakness.llm = LLMRouter(tier="medium", model_override=model_id, timeout_override=35.0)
        weakness_row = await _timed(
            "weakness_detection",
            weakness.detect(
                case["question"],
                case["answer"],
                sprint=1,
                parsed_resume=parsed if isinstance(parsed, dict) else {},
                target_role=case["target_role"],
                years_experience=case["years_experience"],
            ),
            timeout=35.0,
        )
        weakness_result = weakness_row.get("result") if weakness_row.get("ok") else {}
        weakness_row["score"] = 100 if isinstance(weakness_result, dict) and weakness_result.get("severity") and weakness_result.get("probe_direction") else 0
        rows.append(weakness_row)

        discrepancy = DiscrepancyAgent()
        discrepancy.llm = LLMRouter(tier="medium", model_override=model_id, timeout_override=35.0)
        discrepancy_row = await _timed(
            "discrepancy_check",
            discrepancy.check(case["resume"], case["answer"]),
            timeout=35.0,
        )
        discrepancy_result = discrepancy_row.get("result") if discrepancy_row.get("ok") else {}
        discrepancy_row["score"] = 100 if isinstance(discrepancy_result, dict) and discrepancy_result.get("conflict_level") else 0
        rows.append(discrepancy_row)

        reasoning = ReasoningBehaviorAgent()
        reasoning.llm = LLMRouter(tier="medium", model_override=model_id, timeout_override=35.0)
        reasoning_row = await _timed(
            "reasoning_behavior",
            reasoning.evaluate(case["answer"], was_challenged=True),
            timeout=35.0,
        )
        reasoning_result = reasoning_row.get("result") if reasoning_row.get("ok") else {}
        reasoning_row["score"] = 100 if isinstance(reasoning_result, dict) and reasoning_result else 0
        rows.append(reasoning_row)

        app_agent = ApplicationAgent()
        app_agent.llm = LLMRouter(tier="medium", model_override=model_id, timeout_override=40.0)
        app_row = await _timed(
            "application_transfer",
            app_agent.generate(
                implementation_anchor=case["answer"],
                candidate_domain=case["target_role"],
                target_role=case["target_role"],
                years_experience=case["years_experience"],
                resume_snippets=[case["resume"][:500]],
            ),
            timeout=45.0,
        )
        app_result = app_row.get("result")
        if app_row.get("ok") and app_result:
            app_row["score"] = min(len(getattr(app_result, "dimensions", []) or []) * 20, 100)
            app_row["result"] = app_result.to_dict()
        else:
            app_row["score"] = 0
        rows.append(app_row)

        if RUN_MAP and case_index < MAP_CASE_LIMIT:
            map_row = await _timed(
                "interview_map",
                generate_interview_map(
                    resume=case["resume"],
                    session_id=f"bakeoff-{model_id.split('/')[-1]}-{case['name'][:12]}",
                    target_role=case["target_role"],
                ),
                timeout=75.0,
            )
            map_row["score"] = _map_score(map_row.get("result")) if map_row.get("ok") else 0
            if map_row.get("ok") and isinstance(map_row.get("result"), dict):
                compact = dict(map_row["result"])
                compact["focus_areas"] = [
                    {
                        "label": area.get("label"),
                        "focus_key": area.get("focus_key"),
                        "track_source": area.get("track_source"),
                        "track_schema": area.get("track_schema"),
                        "opener": area.get("opener"),
                        "dimension_count": len(area.get("dimensions") or []),
                    }
                    for area in (compact.get("focus_areas") or [])[:5]
                ]
                map_row["result"] = compact
            rows.append(map_row)
    for row in rows:
        row["model"] = model_id
        row["model_label"] = model["label"]
        row["case"] = case["name"]
    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    by_task: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
        by_task.setdefault(row["task"], {}).setdefault(row["model"], []).append(row)

    model_summary = {}
    for model, model_rows in by_model.items():
        scores = [int(r.get("score", 0) or 0) for r in model_rows]
        latencies = [int(r.get("latency_ms", 0) or 0) for r in model_rows if r.get("ok")]
        model_summary[model] = {
            "success_rate": round(sum(1 for r in model_rows if r.get("ok")) / max(len(model_rows), 1), 3),
            "mean_score": round(statistics.mean(scores), 1) if scores else 0,
            "median_latency_ms": round(statistics.median(latencies)) if latencies else None,
            "calls": len(model_rows),
        }

    task_winners = {}
    for task, models in by_task.items():
        ranked = []
        for model, model_rows in models.items():
            scores = [int(r.get("score", 0) or 0) for r in model_rows]
            successes = sum(1 for r in model_rows if r.get("ok"))
            latencies = [int(r.get("latency_ms", 0) or 0) for r in model_rows if r.get("ok")]
            ranked.append({
                "model": model,
                "success_rate": successes / max(len(model_rows), 1),
                "mean_score": statistics.mean(scores) if scores else 0,
                "median_latency_ms": statistics.median(latencies) if latencies else 999999,
            })
        ranked.sort(key=lambda item: (item["success_rate"], item["mean_score"], -item["median_latency_ms"]), reverse=True)
        task_winners[task] = ranked
    return {"model_summary": model_summary, "task_rankings": task_winners}


def _markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = ["# Antigravity Model Bake-off", ""]
    lines.append("## Overall")
    lines.append("| Model | Success | Mean score | Median latency | Calls |")
    lines.append("|---|---:|---:|---:|---:|")
    for model, item in summary["model_summary"].items():
        lines.append(
            f"| `{model}` | {item['success_rate']:.0%} | {item['mean_score']} | "
            f"{item['median_latency_ms'] or 'n/a'} ms | {item['calls']} |"
        )
    lines.append("")
    lines.append("## Task Rankings")
    for task, ranked in summary["task_rankings"].items():
        lines.append(f"### {task}")
        lines.append("| Rank | Model | Success | Mean score | Median latency |")
        lines.append("|---:|---|---:|---:|---:|")
        for idx, item in enumerate(ranked, start=1):
            lines.append(
                f"| {idx} | `{item['model']}` | {item['success_rate']:.0%} | "
                f"{round(item['mean_score'], 1)} | {round(item['median_latency_ms']) if item['median_latency_ms'] != 999999 else 'n/a'} ms |"
            )
        lines.append("")
    failures = [row for row in rows if not row.get("ok")]
    if failures:
        lines.append("## Failures")
        for row in failures[:40]:
            lines.append(f"- `{row['model']}` / `{row['case']}` / `{row['task']}`: {row.get('error_type')} — {row.get('error')}")
    return "\n".join(lines).strip() + "\n"


async def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not available after application env load.")
    rows: list[dict[str, Any]] = []
    cases = _cases()[:CASE_LIMIT]
    for model in MODELS:
        for case_index, case in enumerate(cases):
            print(f"[Bakeoff] {model['id']} :: {case['name']}", flush=True)
            rows.extend(await _run_case(model, case, case_index))
    summary = _summarize(rows)
    out_json = Path("/tmp/antigravity_model_bakeoff_results.json")
    out_md = Path("/tmp/antigravity_model_bakeoff_report.md")
    out_json.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str), encoding="utf-8")
    out_md.write_text(_markdown(summary, rows), encoding="utf-8")
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(_markdown(summary, rows))


if __name__ == "__main__":
    asyncio.run(main())
