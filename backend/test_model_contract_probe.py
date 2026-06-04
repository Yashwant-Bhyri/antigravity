from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

import backend.main  # noqa: F401 - loads project-root env without printing secrets
from backend.agents.application_agent import APPLICATION_SYSTEM
from backend.agents.evaluation_agent import FULL_INTERVIEW_PROMPT
from backend.models.llm_router import JSON_OBJECT_FORMAT, _load_json_lenient
from backend.services.interview_map import _FOCUS_PLAN_SYSTEM, _focus_plan_user_prompt


APPARAO_RESUME = """S V S APPARAO
Education: Indian Institute of Information Technology, Sri City — B.Tech CSE, CGPA 7.51/10.
Product Analyst, Daily Mantra, AppsforBharat, Dec 2024-Present.
- Increased user retention from 25% to 42% through A/B testing and deployment features (Video, Today, AI Guruji).
- Optimized trial-to-subscription conversion from 27% to 42% by reducing trial period from 7 days to 1 day.
- Increased core "Mantra Track End" completion from 27.5% to 55.5% by launching Videos and Today experiments.
- Architected analytics event tracking for Daily Mantra zero-to-one product, defining session flow, engagement, feature adoption, and conversion funnel events.
Associate Business Analyst, AppsforBharat, May 2024-Nov 2024.
- Automated AppsFlyer marketing dashboards for 3 product teams with campaign/ad-set CAC, CPI, CPM, and spend.
- Created executive dashboard integrating impressions, transactions, and conversions.
Computer Vision Intern, IIT Hyderabad, Jun 2024-Aug 2024.
- Processed 400+ highway-road frames using OpenCV, Python, and Tkinter.
- Benchmarked blob tracking, YOLO with SORT, and optical flow.
"""


MESSY_ENGINEER_RESUME = """Name: K.
stuff: built ai things, frontend/backend, cv maybe.
Experience --
AI Engineer Intern @ PixelForge: created prompt workflow for image edits; reduced failed regeneration; had seed control and mask checks; React/Node UI.
ML Project: tiny audio classifier on microcontroller, TensorFlow Lite Micro int8, <10ms target, 95 percent-ish validation.
Research helper: OCR + retrieval notes for scanned forms, some benchmarking, not sure exact metrics.
Skills: python javascript sql react fastapi pytorch opencv lots of APIs.
"""


@dataclass
class ProbeCase:
    name: str
    system: str
    user: str
    max_tokens: int
    validator: str


def _application_user(*, anchor: str, anchor_source: str = "live_answer") -> str:
    return (
        "Target role: Product Analyst\n"
        "Experience level: 1-2 years\n"
        "Candidate domain: product analytics and experimentation\n\n"
        f"Anchor source: {anchor_source}\n\n"
        "Resume context:\n"
        "- Increased retention from 25% to 42% using Video, Today, and AI Guruji experiments.\n"
        "- Optimized trial-to-subscription conversion from 27% to 42% by reducing trial period.\n"
        "- Architected analytics event tracking for session flow, engagement, feature adoption, and conversion funnel.\n\n"
        f"Implementation anchor (what they said they built):\n{anchor}\n\n"
        "Generate the application transfer question and coverage map."
    )


def _evaluation_user() -> str:
    transcript = """
[Sprint 1 | curious_lead]
Q: What denominator did you use for trial conversion?
A: Users who started a trial; success was paid subscription conversion, with cancellation and refund rate as guardrails.

[Sprint 1 | curious_lead]
Q: What else was live when retention moved from 25% to 42%?
A: Video, Today, and AI Guruji were all live, so I would not claim one feature caused the whole move. I checked cohorts by exposure and week.

[Sprint 2 | skeptical_architect]
Q: Imagine cross-platform mantra playback ships tomorrow. How would you measure completion without inflating engagement?
A: I would separate assignment, exposure, and usage. I would stitch logged-in user IDs where possible, mark anonymous-device cases separately, and keep guardrails for refunds, support complaints, and renewal.

[Sprint 2 | skeptical_architect]
Q: How would you explain variance after changing the logic?
A: I would show the old and new definitions side by side, quantify the denominator shift, and call out which portion is measurement change rather than behavior change.

[Sprint 3 | product_lead]
Q: In the CV benchmark, what did you compare?
A: Blob tracking, YOLO with SORT, and optical flow across road-frame sequences, using error profile and compute cost to reason about deployment suitability.
"""
    return f"""RESUME:
{APPARAO_RESUME}

CALIBRATION CONTEXT:
Target role: Product Analyst
Expected years of experience: 1-2 years
Resume-inferred experience tier: early-career

INTERVIEW TRANSCRIPT (5 excerpted turns):
{transcript}

DETECTED WEAKNESSES:
- specificity_gap (medium): Some metric denominators needed follow-up.
- attribution_uncertainty (low): Candidate scoped causal claims rather than overclaiming.

COVERAGE PORTRAIT NOTE: 60% of expected application-transfer dimensions were covered. Voluntary: 2; recovered: 1; missed: 1; incorrect: 0. Use this as important evidence, but make the final verdict from the full transcript context.

Evaluate the full interview."""


SCHEMA_REPAIR_SYSTEM = """You are a strict JSON repair utility.

You will receive malformed or wrongly wrapped JSON that was intended to match a schema.
Repair syntax and shape only. Do not add new reasoning. Preserve the content.
Return one valid JSON object only, with no markdown and no commentary."""


def _schema_repair_user() -> str:
    malformed = """
```json
{
  "ready": true,
  "overall_score": 8.2,
  "top_two_score": 8.0,
  "opener_quality_score": 7.8,
  "dimension_depth_score": 8.4,
  "strengths": ["The primary focus is role-relevant and grounded in Daily Mantra metrics"],
  "issues": ["The taxonomy opener is slightly too broad for a spoken interview"],
  "focus_reviews": [
    {"focus_key": "conversion_lift", "label": "Trial conversion lift", "score": 8.2, "issues": []}
  ],
  "typed_issues": [
    {"issue_scope": "readability_level", "focus_key": "event_taxonomy", "path": "opener", "severity": "minor", "action": "surgical_repair", "reason": "Question has two challenges in one sentence"}
  ],
  "repair_targets": [
    {"focus_key": "event_taxonomy", "path": "opener", "issue": "overpacked opener", "instruction": "Replace with one spoken question about event ownership", "severity": "minor", "issue_scope": "readability_level", "action": "surgical_repair"}
  ]
```
"""
    return (
        "Target schema keys:\n"
        "ready:boolean, overall_score:number, top_two_score:number, opener_quality_score:number, "
        "dimension_depth_score:number, strengths:list[string], issues:list[string], "
        "focus_reviews:list[object], typed_issues:list[object], repair_targets:list[object]\n\n"
        f"Malformed input:\n{malformed}"
    )


def build_cases() -> list[ProbeCase]:
    return [
        ProbeCase(
            name="critic_schema_repair_malformed_json",
            system=SCHEMA_REPAIR_SYSTEM,
            user=_schema_repair_user(),
            max_tokens=1800,
            validator="critic_schema_repair",
        ),
        ProbeCase(
            name="application_primary_live_anchor",
            system=APPLICATION_SYSTEM,
            user=_application_user(
                anchor=(
                    "I defined Daily Mantra events for session start, task discovery, mantra start, "
                    "mantra track end, video exposure, trial start, payment initiated, and subscription success."
                )
            ),
            max_tokens=5000,
            validator="application",
        ),
        ProbeCase(
            name="application_resume_focus_fallback_anchor",
            system=APPLICATION_SYSTEM,
            user=_application_user(
                anchor=(
                    "Daily Mantra product analytics claim: retention moved from 25% to 42%, trial conversion "
                    "from 27% to 42%, and the candidate architected the event taxonomy powering those experiments."
                ),
                anchor_source="resume_focus_fallback",
            ),
            max_tokens=5000,
            validator="application",
        ),
        ProbeCase(
            name="focus_plan_apparao",
            system=_FOCUS_PLAN_SYSTEM,
            user=_focus_plan_user_prompt(resume=APPARAO_RESUME, target_role="Product Analyst"),
            max_tokens=4000,
            validator="focus_plan",
        ),
        ProbeCase(
            name="focus_plan_messy_engineer",
            system=_FOCUS_PLAN_SYSTEM,
            user=_focus_plan_user_prompt(resume=MESSY_ENGINEER_RESUME, target_role="AI Engineer"),
            max_tokens=4000,
            validator="focus_plan",
        ),
        ProbeCase(
            name="final_eval_strong_product_excerpt",
            system=FULL_INTERVIEW_PROMPT,
            user=_evaluation_user(),
            max_tokens=3500,
            validator="evaluation",
        ),
    ]


def validate_payload(kind: str, payload: Any) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not isinstance(payload, dict):
        return False, ["non_json_or_non_object"]

    if kind == "application":
        question = str(payload.get("application_question") or "").strip()
        dims = payload.get("dimensions")
        if len(question.split()) < 18:
            failures.append("application_question_too_short_or_missing")
        if not isinstance(dims, list) or not (4 <= len(dims) <= 6):
            failures.append("dimensions_count_not_4_to_6")
        else:
            for idx, dim in enumerate(dims):
                if not isinstance(dim, dict):
                    failures.append(f"dimension_{idx}_not_object")
                    continue
                if not str(dim.get("id") or "").strip():
                    failures.append(f"dimension_{idx}_missing_id")
                if not str(dim.get("surfacing_question") or "").strip().endswith("?"):
                    failures.append(f"dimension_{idx}_bad_surfacing_question")
                approaches = dim.get("expected_approaches")
                if not isinstance(approaches, list) or len(approaches) < 2:
                    failures.append(f"dimension_{idx}_expected_approaches_too_thin")

    elif kind == "focus_plan":
        areas = payload.get("focus_areas")
        if not isinstance(areas, list) or not (2 <= len(areas) <= 5):
            failures.append("focus_area_count_not_2_to_5")
        else:
            seen_contexts: set[str] = set()
            for idx, area in enumerate(areas):
                if not isinstance(area, dict):
                    failures.append(f"area_{idx}_not_object")
                    continue
                for field in ("label", "focus_key", "anchor_context", "why_priority"):
                    if not str(area.get(field) or "").strip():
                        failures.append(f"area_{idx}_missing_{field}")
                context_key = re.sub(r"[^a-z0-9]+", " ", str(area.get("anchor_context") or "").lower()).strip()[:60]
                if context_key and context_key in seen_contexts:
                    failures.append(f"area_{idx}_possible_duplicate_context")
                seen_contexts.add(context_key)

    elif kind == "evaluation":
        rec = str(payload.get("hire_recommendation") or "").strip().upper().replace("_", " ")
        if rec not in {"HIRE", "MAYBE", "NO HIRE", "INSUFFICIENT DATA"}:
            failures.append("invalid_hire_recommendation")
        try:
            score = float(payload.get("overall_score"))
        except (TypeError, ValueError):
            failures.append("overall_score_not_numeric")
            score = -1
        if score < 3 and rec == "NO HIRE":
            failures.append("suspicious_near_zero_no_hire_on_substantive_excerpt")
        if not isinstance(payload.get("risk_flags"), list):
            failures.append("risk_flags_not_list")
        if not isinstance(payload.get("strengths"), list):
            failures.append("strengths_not_list")

    elif kind == "critic_schema_repair":
        for key in ("ready", "overall_score", "top_two_score", "focus_reviews", "typed_issues", "repair_targets"):
            if key not in payload:
                failures.append(f"missing_{key}")
        if not isinstance(payload.get("ready"), bool):
            failures.append("ready_not_boolean")
        for key in ("overall_score", "top_two_score"):
            try:
                float(payload.get(key))
            except (TypeError, ValueError):
                failures.append(f"{key}_not_numeric")
        for key in ("focus_reviews", "typed_issues", "repair_targets", "strengths", "issues"):
            if key in payload and not isinstance(payload.get(key), list):
                failures.append(f"{key}_not_list")
        if isinstance(payload.get("typed_issues"), list):
            allowed_scopes = {"plan_level", "track_level", "field_level", "readability_level", "weighting_level"}
            for idx, issue in enumerate(payload["typed_issues"]):
                if not isinstance(issue, dict) or issue.get("issue_scope") not in allowed_scopes:
                    failures.append(f"typed_issue_{idx}_bad_scope")

    return not failures, failures


async def call_model(client: AsyncOpenAI, model: str, case: ProbeCase) -> dict:
    started = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=case.max_tokens,
            response_format=JSON_OBJECT_FORMAT,
            messages=[
                {"role": "system", "content": case.system},
                {"role": "user", "content": case.user},
            ],
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = (response.choices[0].message.content or "").strip()
        parsed = _load_json_lenient(text)
        ok, failures = validate_payload(case.validator, parsed)
        return {
            "model": model,
            "case": case.name,
            "ok": ok,
            "failures": failures,
            "elapsed_ms": elapsed_ms,
            "raw_chars": len(text),
            "parsed_type": type(parsed).__name__,
            "preview": json.dumps(parsed, ensure_ascii=True)[:900] if parsed is not None else text[:900],
        }
    except Exception as exc:
        return {
            "model": model,
            "case": case.name,
            "ok": False,
            "failures": [f"{type(exc).__name__}: {str(exc)[:300]}"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "raw_chars": 0,
            "parsed_type": "error",
            "preview": "",
        }


def write_reports(rows: list[dict]) -> None:
    prefix = Path(os.environ.get("PROBE_OUTPUT_PREFIX", "/tmp/antigravity_model_contract_probe"))
    json_path = prefix.with_suffix(".json")
    md_path = prefix.with_suffix(".md")
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding="utf-8")
    lines = [
        "# Antigravity Model Contract Probe",
        "",
        "| Model | Case | OK | Latency ms | Failures |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        failures = "; ".join(row.get("failures") or [])
        lines.append(
            f"| `{row['model']}` | `{row['case']}` | {row['ok']} | {row['elapsed_ms']} | {failures} |"
        )
    lines.extend(["", f"JSON: `{json_path}`"])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ModelProbe] Wrote {json_path}")
    print(f"[ModelProbe] Wrote {md_path}")


async def main() -> None:
    models = [
        model.strip()
        for model in os.environ.get(
            "PROBE_MODELS",
            "deepseek/deepseek-v4-pro,google/gemini-3.1-pro-preview",
        ).split(",")
        if model.strip()
    ]
    client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        timeout=float(os.environ.get("MODEL_PROBE_TIMEOUT_SECONDS", "180")),
    )
    cases = build_cases()
    case_filter = {
        key.strip()
        for key in os.environ.get("PROBE_CASES", "").split(",")
        if key.strip()
    }
    if case_filter:
        cases = [case for case in cases if case.name in case_filter]
        if not cases:
            raise RuntimeError(f"PROBE_CASES did not match any probe cases: {sorted(case_filter)}")
    rows: list[dict] = []
    for model in models:
        for case in cases:
            print(f"[ModelProbe] {model} :: {case.name}")
            rows.append(await call_model(client, model, case))
    write_reports(rows)
    passed = sum(1 for row in rows if row.get("ok"))
    print(f"[ModelProbe] Passed {passed}/{len(rows)} checks")


if __name__ == "__main__":
    asyncio.run(main())
