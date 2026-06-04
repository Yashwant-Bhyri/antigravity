"""
Paid probe for first-pass resume surface planning models.

This is intentionally not part of the product path yet. It compares candidate
models for a small, typed extraction task:

resume -> focus areas -> sub-focus areas -> testable surfaces

Run:
  PYTHONPATH=. python3 backend/test_surface_planner_model_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

# Importing backend.main applies the project env loader without printing secrets.
import backend.main  # noqa: F401
from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter


MODELS = [
    "openai/gpt-5-mini",
    "openai/gpt-5.4-mini",
    "openai/gpt-chat-latest",
]


CASES = [
    {
        "key": "marketplace_growth",
        "target_role": "Product Analytics Engineer",
        "years_experience": "2.8",
        "resume": """
TANVI MENON
Analytics Engineer, QuickKart Marketplace
- Built seller onboarding event taxonomy: signup, KYC submit, first listing, listing approved, first order.
- Reported seller activation improved from 22% to 38% after checklist, support-call, and KYC UX changes.
- Created BigQuery/dbt models joining seller events, support tickets, KYC status, and listing approvals.
- Owned metric definitions and analysis; platform engineering owned event SDK and dbt deployment.
- Built marketplace health dashboard for seller activation, buyer conversion, first-order lag, refunds, and support SLA.
- Claimed "reduced first-order lag by 31%," but rollout overlapped with seller-support staffing changes.
- Side project: OCR invoice parser using Tesseract and Python, not production deployed.
- College CV project: pothole classifier from starter notebook.
""".strip(),
        "expected": {
            "must_hit": ["activation", "taxonomy", "dashboard", "dbt"],
            "off_role": ["ocr", "pothole", "cv"],
        },
    },
    {
        "key": "apparao_product",
        "target_role": "Product Analyst",
        "years_experience": "2.5",
        "resume": """
APPARAO V.
Product Analyst, DailyMantra Wellness App
- Reduced free trial from 7 days to 1 day; paid conversion moved from 27% to 42%.
- Built activation and retention dashboards across Track Start, Track End, Videos, Today tab, and trial conversion.
- Defined event taxonomy for trial start, subscription start, track completion, video view, refund, and churn risk.
- Partnered with product and growth teams on guardrails: refund rate, D7 retention, cancellation reason, and support tickets.
- Internship: computer vision research using YOLO/blob tracking for traffic videos.
""".strip(),
        "expected": {
            "must_hit": ["conversion", "retention", "taxonomy", "dashboard"],
            "off_role": ["computer vision", "yolo", "blob"],
        },
    },
    {
        "key": "technical_ai",
        "target_role": "AI Systems Engineer",
        "years_experience": "3.0",
        "resume": """
RHEA SINGH
AI Workflow Engineer, ClipForge
- Built video editing workflow orchestration for prompt-to-shot generation, timeline edits, and render status tracking.
- Integrated model APIs into a web editor; owned retries, queueing, progress streaming, and failure recovery.
- Improved render-success rate from 81% to 94% by redesigning job state transitions and retry policies.
- Worked with model team but did not train diffusion models or modify model weights.
- Side project: TinyML audio classifier using INT8 quantization on a microcontroller.
""".strip(),
        "expected": {
            "must_hit": ["workflow", "queue", "retry", "render"],
            "off_role": ["model weights", "diffusion training"],
        },
    },
    {
        "key": "average_partial_candidate",
        "target_role": "Product Data Analyst",
        "years_experience": "2.2",
        "resume": """
NEHA R.
Product Data Analyst, FinPay
- Maintained onboarding funnel dashboard for KYC start, KYC submit, bank-link success, first transaction, and failed-payment reasons.
- Helped analyze a signup-form simplification that improved KYC submit rate from 48% to 57%, but the rollout was not randomized.
- Wrote SQL for weekly stakeholder reports and investigated data quality issues in payment-failure events.
- Supported PMs with ad hoc cohort charts; did not own final product decisions.
- College project: movie recommendation model using collaborative filtering.
""".strip(),
        "expected": {
            "must_hit": ["onboarding", "kyc", "dashboard", "sql"],
            "off_role": ["recommendation", "collaborative filtering"],
        },
    },
    {
        "key": "honest_gap_corrected",
        "target_role": "Growth Analyst",
        "years_experience": "2.6",
        "resume": """
KARTHIK M.
Growth Analyst, LearnLoop
- Resume says "owned pricing experiment that increased revenue by 18%."
- In reality, PM owned pricing; candidate owned analysis, cohort cuts, and guardrail dashboard for refunds, cancellation, and support tickets.
- Built Mixpanel and BigQuery reports for trial starts, paid conversion, coupon usage, and D14 retention.
- Identified that one coupon campaign inflated top-line revenue but reduced renewal quality.
- Side project: neural style transfer app copied from a tutorial.
""".strip(),
        "expected": {
            "must_hit": ["pricing", "revenue", "guardrail", "coupon"],
            "off_role": ["neural style", "tutorial"],
        },
    },
    {
        "key": "trap_inflated_claim",
        "target_role": "Data Analyst",
        "years_experience": "1.8",
        "resume": """
ARJUN K.
Data Analyst, GrowthStack
- Architected AI-powered RAG analytics platform that increased revenue by 300%.
- Built OCR, dashboard, ML forecasting, customer segmentation, and automated reporting.
- Owned all stakeholder decisions and scaled data from 0 to millions of users.
- Created dashboards in Sheets and Looker Studio for weekly campaign reporting.
- Internship project: SQL joins, cohort charts, and campaign tagging cleanup.
""".strip(),
        "expected": {
            "must_hit": ["dashboard", "campaign", "sql", "ownership"],
            "off_role": ["rag", "ocr", "300"],
        },
    },
]


EDGE_CASES = [
    {
        "key": "regulated_health_ops",
        "target_role": "Product Data Analyst",
        "years_experience": "3.1",
        "resume": """
MEERA JOSHI
Data Analyst, CareBridge Clinics
- Built appointment no-show and follow-up adherence dashboards across clinics, doctors, patient age bands, reminder channels, and insurance/payment status.
- Reported "reduced no-shows by 19%" after WhatsApp reminders, call-center callback changes, and new appointment-slot rules launched in the same month.
- Created SQL models joining appointments, call logs, reminder sends, doctor schedules, and billing outcomes.
- Worked with compliance on de-identifying patient-level exports; did not own clinical policy or EHR event instrumentation.
- Side project: chest X-ray pneumonia classifier from a Kaggle notebook.
- Volunteer: designed posters for a blood donation camp.
""".strip(),
        "expected": {
            "must_hit": ["no-show", "adherence", "dashboard", "sql"],
            "off_role": ["x-ray", "pneumonia", "kaggle", "posters"],
        },
    },
    {
        "key": "vendor_ai_no_internals",
        "target_role": "AI Product Engineer",
        "years_experience": "2.9",
        "resume": """
AADIT RAO
AI Product Engineer, VoiceDesk
- Integrated third-party LLM and speech APIs into a customer-support copilot; owned routing, latency tracing, fallback messaging, and agent handoff flows.
- Improved median first-response latency from 4.8s to 2.1s by caching retrieval snippets, prefetching TTS, and cutting redundant API calls.
- Built evaluation dashboards for containment rate, escalation quality, hallucination flags, CSAT, and agent override reasons.
- Did not train LLMs, tune model weights, or build the speech model; vendor and ML platform teams owned those layers.
- Hackathon: built a toy transformer from a tutorial.
""".strip(),
        "expected": {
            "must_hit": ["routing", "latency", "fallback", "evaluation"],
            "off_role": ["model weights", "speech model", "toy transformer", "tutorial"],
        },
    },
    {
        "key": "messy_multilingual_resume",
        "target_role": "Growth Analyst",
        "years_experience": "2.4",
        "resume": """
PRIYA NAIR
Experience:
1) Growth Analytics - LocalDukaan (Hindi/English app for kirana orders)
   * "GMV badh gaya 41%" after free-delivery banner, coupon copy, and delivery-slot cleanup.
   * Made funnel sheet: app_open -> product_view -> add_to_cart -> order_place -> delivered. Used SQL + Metabase.
   * Learned later that COD orders and cancelled deliveries were mixed in GMV dashboard; fixed denominator with finance team.
2) Internship - campus ML club: face-mask detector, OpenCV, not used in production.
Skills: Excel, SQL, Python basics, storytelling, Canva, teamwork.
""".strip(),
        "expected": {
            "must_hit": ["gmv", "coupon", "funnel", "denominator"],
            "off_role": ["face-mask", "opencv", "canva"],
        },
    },
    {
        "key": "design_ops_hybrid",
        "target_role": "Product Operations Analyst",
        "years_experience": "3.5",
        "resume": """
SANA KHAN
Product Ops / UX Research Analyst, EduMint
- Ran weekly learning-health review for course starts, lesson completion, refund tickets, mentor response SLA, and placement-readiness milestones.
- Claimed "redesigned onboarding and improved lesson completion by 24%"; actual work included research synthesis, dashboard instrumentation requests, and experiment readout, while design owned UI changes.
- Built Airtable/Looker dashboards for mentor queues, refund reasons, and placement support bottlenecks.
- Created qualitative interview tags for 80 learner calls and mapped them to quantitative drop-off points.
- Side portfolio: Figma landing page redesigns and a Dribbble case study.
""".strip(),
        "expected": {
            "must_hit": ["lesson completion", "refund", "mentor", "dashboard"],
            "off_role": ["figma", "dribbble", "landing page"],
        },
    },
    {
        "key": "senior_hype_thin_evidence",
        "target_role": "Senior Data Analyst",
        "years_experience": "4.2",
        "resume": """
VIKRAM S.
Senior Data Analyst, NeoBank
- Architected risk analytics engine preventing fraud losses of $2.4M.
- Automated underwriting dashboard, repayment cohort analysis, delinquency segmentation, and dispute reporting.
- Led 8 stakeholders across risk, ops, finance, and product; owned "all credit decisions" according to resume.
- Actual tools listed: Excel, SQL, Python notebooks, Power BI. No model deployment detail.
- Built OCR loan-document parser as weekend project; not connected to bank systems.
- College robotics prize.
""".strip(),
        "expected": {
            "must_hit": ["risk", "underwriting", "repayment", "delinquency"],
            "off_role": ["ocr", "robotics", "all credit decisions"],
        },
    },
]


SYSTEM_PROMPT = """
You are an interview planning analyst. Extract the few high-signal interview
surfaces from a resume for the target role.

Do not generate interview questions.
Do not scan every line equally.
Do not over-reward buzzwords, side projects, or off-role artifacts.
Do not use allocation hints as question counts.

Return only valid JSON with this shape:
{
  "focus_areas": [
    {
      "focus_key": "short_snake_case",
      "label": "plain label",
      "why_high_signal": "why this changes hiring signal for the target role",
      "role_relevance": 1-5,
      "profile_importance": 1-5,
      "evidence_strength": 1-5,
      "claim_risk": 1-5,
      "recommended_allocation_hint": 0.0-1.0,
      "source_snippets": ["exact resume snippet"],
      "sub_focuses": [
        {
          "sub_focus_key": "short_snake_case",
          "label": "plain label",
          "surface_kind": "attribution|taxonomy|dashboard|data_modeling|ownership_boundary|implementation_depth|metric_design|technical_systems|other",
          "why_test": "what this tests",
          "testable_surfaces": ["specific surface to test"],
          "source_snippets": ["exact resume snippet"]
        }
      ]
    }
  ],
  "demoted_or_off_role_surfaces": [
    {
      "label": "plain label",
      "reason": "why it should not lead the interview",
      "source_snippets": ["exact resume snippet"]
    }
  ],
  "missing_or_risky_checks": ["important checks likely needed in interview"],
  "planning_notes": "short note on focus ranking"
}

Quality target:
- 3 to 5 focus areas total.
- Each focus area should have 1 to 3 sub-focuses.
- The top 2 focus areas should cover most of the role-relevant hiring signal.
- Prefer broad high-signal surfaces over trivia like exact SQL file names.
- Use source snippets; do not invent claims.
""".strip()


def _user_prompt(case: dict[str, Any]) -> str:
    return f"""
Target role: {case['target_role']}
Years experience: {case['years_experience']}

Resume:
{case['resume']}

Extract the high-signal focus areas, sub-focus areas, and testable surfaces.
""".strip()


def _fetch_prices() -> dict[str, dict[str, float]]:
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=20) as response:
            payload = json.load(response)
    except Exception:
        return {}
    prices: dict[str, dict[str, float]] = {}
    for item in payload.get("data", []):
        model_id = item.get("id")
        pricing = item.get("pricing") or {}
        if model_id in _selected_models():
            try:
                prices[model_id] = {
                    "prompt": float(pricing.get("prompt") or 0.0),
                    "completion": float(pricing.get("completion") or 0.0),
                }
            except (TypeError, ValueError):
                prices[model_id] = {"prompt": 0.0, "completion": 0.0}
    return prices


def _contains_any(text: str, needles: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for item in needles if item.lower() in lowered)


def _score_plan(plan: Any, case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {
            "score": 0,
            "status": "invalid_shape",
            "reasons": ["response was not a JSON object"],
        }

    focus_areas = plan.get("focus_areas")
    if not isinstance(focus_areas, list):
        return {
            "score": 0,
            "status": "missing_focus_areas",
            "reasons": ["focus_areas missing or not a list"],
        }

    text = json.dumps(plan, sort_keys=True).lower()
    expected = case["expected"]
    reasons: list[str] = []
    score = 0

    focus_count = len(focus_areas)
    if 3 <= focus_count <= 5:
        score += 10
    else:
        reasons.append(f"focus_count={focus_count}, expected 3-5")

    must_hit_count = _contains_any(text, expected["must_hit"])
    score += min(must_hit_count, len(expected["must_hit"])) * 10
    if must_hit_count < max(2, len(expected["must_hit"]) - 1):
        reasons.append(f"missed important signals: {expected['must_hit']}")

    off_role_mentions = _contains_any(
        json.dumps(plan.get("demoted_or_off_role_surfaces", []), sort_keys=True),
        expected["off_role"],
    )
    if off_role_mentions:
        score += min(off_role_mentions, len(expected["off_role"])) * 5
    else:
        reasons.append(f"did not explicitly demote off-role/risky surfaces: {expected['off_role']}")

    top_two_text = json.dumps(focus_areas[:2], sort_keys=True).lower()
    top_off_role = _contains_any(top_two_text, expected["off_role"])
    if top_off_role:
        reasons.append("top two focus areas include off-role or hype-heavy surface")
    else:
        score += 15

    sub_focus_total = 0
    sourced_count = 0
    allocation_ok = True
    for area in focus_areas:
        if isinstance(area, dict):
            subs = area.get("sub_focuses") or []
            if isinstance(subs, list):
                sub_focus_total += len(subs)
            if area.get("source_snippets"):
                sourced_count += 1
            try:
                allocation = float(area.get("recommended_allocation_hint"))
                if allocation < 0 or allocation > 1:
                    allocation_ok = False
            except (TypeError, ValueError):
                allocation_ok = False

    if sub_focus_total >= focus_count:
        score += 10
    else:
        reasons.append("sub-focus coverage is too thin")

    if sourced_count >= max(2, focus_count - 1):
        score += 10
    else:
        reasons.append("source snippets are thin")

    if allocation_ok:
        score += 5
    else:
        reasons.append("allocation hints missing or invalid")

    low_signal_terms = [
        "specific sql script",
        "file name",
        "which event property did you add later",
        "most confident",
    ]
    low_signal_hits = [term for term in low_signal_terms if term in text]
    if low_signal_hits:
        reasons.append(f"low-signal planning language appeared: {low_signal_hits}")
    else:
        score += 10

    return {
        "score": min(score, 100),
        "status": "ok" if score >= 75 and not top_off_role else "review",
        "reasons": reasons,
        "focus_count": focus_count,
        "sub_focus_total": sub_focus_total,
        "must_hit_count": must_hit_count,
        "off_role_demotions": off_role_mentions,
        "top_two": [
            {
                "focus_key": area.get("focus_key"),
                "label": area.get("label"),
                "sub_focuses": [
                    sub.get("label")
                    for sub in (area.get("sub_focuses") or [])[:3]
                    if isinstance(sub, dict)
                ],
            }
            for area in focus_areas[:2]
            if isinstance(area, dict)
        ],
    }


async def _run_one(model_id: str, case: dict[str, Any], prices: dict[str, dict[str, float]]) -> dict[str, Any]:
    router = LLMRouter(tier="small", model_override=model_id, timeout_override=90.0)
    started = time.perf_counter()
    error = ""
    value: Any = None
    try:
        value = await router.call(
            SYSTEM_PROMPT,
            _user_prompt(case),
            max_tokens=int(os.environ.get("SURFACE_PROBE_MAX_TOKENS", "2200")),
            response_format=JSON_OBJECT_FORMAT,
            audit_call_name="surface_planner_model_probe",
            audit_session_id=f"surface-probe-{case['key']}",
            audit_metadata={"probe_model": model_id, "case": case["key"]},
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:500]}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    score = _score_plan(value, case) if not error else {
        "score": 0,
        "status": "error",
        "reasons": [error],
    }
    prompt_estimate = len(SYSTEM_PROMPT + _user_prompt(case)) / 4
    completion_estimate = len(json.dumps(value)) / 4 if value is not None else 0
    price = prices.get(model_id, {})
    estimated_cost = (
        prompt_estimate * float(price.get("prompt", 0.0))
        + completion_estimate * float(price.get("completion", 0.0))
    )
    return {
        "model": model_id,
        "case": case["key"],
        "target_role": case["target_role"],
        "elapsed_ms": elapsed_ms,
        "ok": not error and isinstance(value, dict),
        "error": error,
        "estimated_cost_usd": round(estimated_cost, 6),
        "quality": score,
        "plan": value,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
    summary = {}
    for model, model_rows in by_model.items():
        scores = [int(row["quality"].get("score", 0)) for row in model_rows]
        latencies = [float(row.get("elapsed_ms") or 0.0) for row in model_rows]
        costs = [float(row.get("estimated_cost_usd") or 0.0) for row in model_rows]
        summary[model] = {
            "calls": len(model_rows),
            "success_rate": round(sum(1 for row in model_rows if row.get("ok")) / max(len(model_rows), 1), 3),
            "mean_score": round(sum(scores) / max(len(scores), 1), 1),
            "min_score": min(scores) if scores else 0,
            "mean_latency_ms": round(sum(latencies) / max(len(latencies), 1), 1),
            "estimated_total_cost_usd": round(sum(costs), 6),
        }
    return summary


def _write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# Surface Planner Model Probe",
        "",
        "Task: resume -> focus areas -> sub-focus areas -> testable surfaces.",
        "",
        "## Model Summary",
        "",
        "| Model | Success | Mean Score | Min Score | Mean Latency | Est Cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, item in payload["summary"].items():
        lines.append(
            f"| `{model}` | {item['success_rate']:.0%} | {item['mean_score']} | "
            f"{item['min_score']} | {item['mean_latency_ms']} ms | "
            f"${item['estimated_total_cost_usd']:.6f} |"
        )
    lines.extend(["", "## Case Results", ""])
    for row in payload["rows"]:
        quality = row["quality"]
        lines.extend([
            f"### `{row['model']}` / `{row['case']}`",
            "",
            f"- Score: {quality.get('score')} ({quality.get('status')})",
            f"- Latency: {row['elapsed_ms']} ms",
            f"- Estimated cost: ${row['estimated_cost_usd']:.6f}",
            f"- Top two: `{json.dumps(quality.get('top_two', []), ensure_ascii=False)}`",
        ])
        reasons = quality.get("reasons") or []
        if reasons:
            lines.append(f"- Review notes: {'; '.join(str(reason) for reason in reasons)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _selected_models() -> list[str]:
    raw = os.environ.get("SURFACE_PROBE_MODELS", "").strip()
    if not raw:
        return MODELS
    return [item.strip() for item in raw.split(",") if item.strip()]


def _selected_cases() -> list[dict[str, Any]]:
    case_set = os.environ.get("SURFACE_PROBE_CASE_SET", "default").strip().lower()
    if case_set in {"edge", "edges", "edge_cases"}:
        return EDGE_CASES
    if case_set in {"all", "all_cases"}:
        return CASES + EDGE_CASES
    return CASES


async def main() -> None:
    models = _selected_models()
    cases = _selected_cases()
    prices = _fetch_prices()
    rows: list[dict[str, Any]] = []
    for model_id in models:
        for case in cases:
            print(f"[SurfaceProbe] {model_id} :: {case['key']}", flush=True)
            rows.append(await _run_one(model_id, case, prices))
    payload = {
        "models": models,
        "prices": prices,
        "cases": [
            {
                "key": case["key"],
                "target_role": case["target_role"],
                "expected": case["expected"],
            }
            for case in cases
        ],
        "summary": _summarize(rows),
        "rows": rows,
    }
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_json = Path(f"/tmp/antigravity_surface_planner_probe_{timestamp}.json")
    out_md = Path(f"/tmp/antigravity_surface_planner_probe_{timestamp}.md")
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(payload, out_md)
    print(f"[SurfaceProbe] wrote {out_json}")
    print(f"[SurfaceProbe] wrote {out_md}")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
