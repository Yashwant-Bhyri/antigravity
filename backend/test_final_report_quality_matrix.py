from __future__ import annotations

import asyncio
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

import backend.main  # noqa: F401 - loads project environment without exposing secrets.
from backend.agents.evaluation_agent import EvaluationAgent
from backend.models.llm_router import LLMRouter


MODEL_CANDIDATES: dict[str, str] = {
    "sonnet_46": "anthropic/claude-sonnet-4.6",
    "gemini_31_pro": "google/gemini-3.1-pro-preview",
    "gemini_35_flash": "google/gemini-3.5-flash",
}


def _coverage(**overrides: Any) -> dict[str, Any]:
    base = {
        "application_transfer_served": True,
        "coverage_dimensions": 4,
        "coverage_evaluated_dimensions": 2,
        "coverage_surfaced_dimensions": 2,
        "coverage_score": 0.58,
        "distinct_focuses": 2,
        "distinct_surfaces": 3,
        "high_value_surfaces_available_count": 3,
        "high_value_surfaces_tested_count": 2,
        "dominant_focus_ratio": 0.50,
        "max_same_surface_streak": 3,
        "breadth_viable": True,
        "full_breadth_viable": True,
        "history_len": 15,
    }
    base.update(overrides)
    return base


def _coverage_map(score: float = 0.58, states: list[str] | None = None) -> dict[str, Any]:
    states = states or ["voluntary", "recovered_surface", "missed", "not_evaluated"]
    labels = [
        "Metric denominator and attribution",
        "Guardrail and unintended effect handling",
        "Operational rollout constraints",
        "Stakeholder decision use",
    ]
    dims = []
    for index, state in enumerate(states):
        dims.append({
            "id": f"d{index + 1}",
            "label": labels[index % len(labels)],
            "description": f"Assesses {labels[index % len(labels)].lower()}.",
            "expected_approaches": ["clear denominator", "tradeoff handling", "role-relevant constraints"],
            "surfacing_question": "How would you test this in a new product context?",
            "weight": 1.0,
            "coverage_state": state,
            "candidate_response": "Candidate provided partial but relevant evidence." if state != "not_evaluated" else "",
            "surfacing_attempted": state != "not_evaluated",
        })
    return {
        "application_question": "How would you transfer this approach to a new paid onboarding flow?",
        "implementation_anchor": "Role-relevant analytics implementation",
        "coverage_score": score,
        "coverage_confidence": 0.68,
        "total_weight": float(len(dims)),
        "dimensions": dims,
    }


def _score(
    turn: int,
    score: float,
    route: str,
    focus: str,
    sub_focus: str,
    excerpt: str,
    weakness: str = "",
) -> dict[str, Any]:
    return {
        "turn_number": turn,
        "turn_id": f"t{turn}",
        "score": score,
        "confidence": 0.66,
        "route_kind": route,
        "focus_label": focus,
        "sub_focus_label": sub_focus,
        "answer_excerpt": excerpt[:260],
        "weakness_severity": weakness,
        "breakdown": {
            "specificity": score,
            "causal_reasoning": max(1.0, min(10.0, score + 0.2)),
            "ownership_clarity": max(1.0, min(10.0, score - 0.1)),
        },
    }


def _turn(
    n: int,
    question: str,
    answer: str,
    route: str,
    focus: str,
    sub_focus: str,
) -> dict[str, Any]:
    return {
        "turn_id": f"t{n}",
        "turn_number": n,
        "question": question,
        "answer": answer,
        "route_kind": route,
        "focus_key": focus.lower().replace(" ", "_"),
        "focus_label": focus,
        "sub_focus_key": sub_focus.lower().replace(" ", "_"),
        "sub_focus_label": sub_focus,
    }


def _base_product_history() -> list[dict[str, Any]]:
    return [
        _turn(1, "Tell me about the product work you are proudest of.", "The Daily Mantra retention work is the best example because I owned the analysis loop, not the whole product. We moved retention from 25% to 42% by segmenting cohorts and testing video and today surfaces.", "warm_open", "Daily Mantra", "Product analytics"),
        _turn(2, "Your conversion improved from 27% to 42%; what moved that lift?", "The biggest lever was reducing the trial from 7 days to 1 day, but I treated trial starters as the denominator and tracked cancellation, refund, and day-7 engagement as guardrails.", "primary_depth", "Daily Mantra", "Conversion experiment"),
        _turn(3, "How did you know the lift was not just channel mix?", "I split by acquisition channel and campaign week. The strongest lift was consistent in the largest paid cohorts, though some smaller organic cohorts were too noisy for strong claims.", "primary_depth", "Daily Mantra", "Attribution"),
        _turn(4, "What exactly did you instrument for the event taxonomy?", "I defined session start, task discovery, mantra play start, track end, subscription intent, and trial start. Engineering implemented the SDK events; I wrote definitions, QA checks, and funnel logic.", "primary_depth", "Daily Mantra", "Event taxonomy"),
        _turn(5, "Apply that to a new paid onboarding flow with weak activation.", "I would start with activation definition, instrument the path to first value, run a friction audit, create cohort baselines, and test a shorter commitment moment only with churn and complaint guardrails.", "application_transfer", "Daily Mantra", "Application transfer"),
        _turn(6, "What guardrail could make the result look good but be bad?", "Higher trial conversion could hide worse retained revenue if refunds or post-trial cancellations rise, so I would separate immediate conversion from paid retention and LTV.", "coverage_surface", "Daily Mantra", "Guardrails"),
        _turn(7, "How would you handle late or duplicate events?", "I would define event IDs and server timestamps where possible, dedupe by user-event-time windows, and reconcile Mixpanel counts against backend subscription tables.", "coverage_depth", "Daily Mantra", "Data quality"),
        _turn(8, "Tell me about your AppsFlyer dashboard work.", "The dashboard joined campaign spend, ad set metadata, impressions, installs, and transaction signals so teams could pause poor campaigns faster.", "second_anchor", "Marketing dashboards", "Dashboard automation"),
        _turn(9, "What was hardest about that dashboard?", "Attribution windows and naming mismatches. We had to normalize campaign IDs and show freshness so business teams did not overreact to partial-day data.", "second_anchor", "Marketing dashboards", "Attribution dashboard"),
        _turn(10, "What decision did it actually change?", "Teams could compare CAC and transactions daily instead of waiting for manual reports, which reduced reporting time from roughly 20 minutes to under 5 minutes.", "coverage_surface", "Marketing dashboards", "Decision use"),
        _turn(11, "Where are you least certain in these claims?", "I am less certain about assigning all retention lift to one feature because multiple launches overlapped. I am more confident in event definitions and funnel movement.", "synthesis_close", "Daily Mantra", "Claim calibration"),
        _turn(12, "What would you want to test next?", "I would test whether video creates repeat habit or only novelty by separating new-user activation from week-two repeat sessions.", "synthesis_close", "Daily Mantra", "Next experiment"),
    ]


def _fixtures() -> dict[str, dict[str, Any]]:
    product_history = _base_product_history()
    product_scores = [
        _score(i + 1, score, turn["route_kind"], turn["focus_label"], turn["sub_focus_label"], turn["answer"])
        for i, (turn, score) in enumerate(zip(product_history, [7.2, 8.0, 7.4, 7.8, 8.1, 7.6, 7.3, 7.2, 7.0, 7.1, 7.5, 7.7]))
    ]

    tunneled_history = product_history[:1] + [
        _turn(2, "Why did CV blob tracking have a high error rate?", "It was a research internship. I can explain it, but it is not my strongest product analyst evidence.", "primary_depth", "Computer Vision", "CV benchmarking"),
        _turn(3, "But why did YOLO with SORT differ from optical flow?", "Because they handle object identity differently, but again my stronger recent work is product analytics.", "primary_depth", "Computer Vision", "CV benchmarking"),
        _turn(4, "What exactly failed in the CV methods?", "Mostly occlusion and lane-boundary ambiguity. I did not deploy this in production.", "primary_depth", "Computer Vision", "CV benchmarking"),
        _turn(5, "Can you defend the CV benchmark more deeply?", "Only partially. I was an intern on a research comparison, not the owner of a product system.", "primary_depth", "Computer Vision", "CV benchmarking"),
    ]
    tunneled_scores = [
        _score(i + 1, score, turn["route_kind"], turn["focus_label"], turn["sub_focus_label"], turn["answer"], "medium")
        for i, (turn, score) in enumerate(zip(tunneled_history, [6.5, 4.5, 4.4, 4.2, 4.1]))
    ]

    honest_history = [
        _turn(1, "You wrote that you architected analytics tracking. What did you personally own?", "I should narrow that. I did not architect the whole backend. I owned the event definitions, QA, and funnel interpretation; engineering owned SDK implementation.", "warm_open", "Growth analytics", "Ownership calibration"),
        _turn(2, "What was the strongest real implementation piece?", "The strongest owned part was defining activation and subscription funnel events, then building checks that caught missing track-end events.", "primary_depth", "Growth analytics", "Event taxonomy"),
        _turn(3, "How would you transfer that to another product?", "I would first define the business-critical action, then instrument the path, validate against source-of-truth tables, and only then run experiments.", "application_transfer", "Growth analytics", "Application transfer"),
        _turn(4, "What would you not claim credit for?", "I would not claim I built the data warehouse or shipped SDK code. I influenced requirements and validation.", "coverage_surface", "Growth analytics", "Honest boundary"),
        _turn(5, "Tell me about dashboard work outside that claim.", "I built a campaign dashboard that helped teams compare CAC, spend, installs, and conversion daily.", "second_anchor", "Marketing dashboards", "Dashboard automation"),
        _turn(6, "Where did that dashboard help decisions?", "It helped pause underperforming ad sets quickly and made daily campaign reviews less manual.", "synthesis_close", "Marketing dashboards", "Decision use"),
    ]
    honest_scores = [
        _score(i + 1, score, turn["route_kind"], turn["focus_label"], turn["sub_focus_label"], turn["answer"])
        for i, (turn, score) in enumerate(zip(honest_history, [6.8, 7.4, 7.2, 7.0, 6.9, 6.8]))
    ]

    trap_history = [
        _turn(1, "You claim AI RAG, OCR, and dashboards drove 80% revenue lift. What did you own?", "I was involved across the stack and coordinated the AI strategy with stakeholders.", "warm_open", "AI revenue platform", "Ownership"),
        _turn(2, "What was the denominator for the 80% lift?", "It was based on overall business impact and leadership tracked it internally.", "primary_depth", "AI revenue platform", "Metric denominator"),
        _turn(3, "Describe the RAG evaluation setup.", "We used embeddings and checked that answers were good for users.", "primary_depth", "AI revenue platform", "RAG evaluation"),
        _turn(4, "What exact failure mode did you fix?", "The system had some hallucinations and OCR issues, and we improved the pipeline.", "primary_depth", "AI revenue platform", "Failure mode"),
        _turn(5, "Apply this to a claims-processing workflow.", "I would use RAG and OCR to automate everything and improve accuracy.", "application_transfer", "AI revenue platform", "Application transfer"),
        _turn(6, "How would you measure accuracy separately from throughput?", "We would look at accuracy dashboards and user feedback.", "coverage_surface", "AI revenue platform", "Measurement"),
        _turn(7, "What was your second strongest project?", "I also built dashboards that helped the company make decisions.", "second_anchor", "Dashboards", "Dashboard ownership"),
        _turn(8, "What joins and data quality checks did those dashboards need?", "They joined the necessary data and had filters for teams.", "coverage_depth", "Dashboards", "Data quality"),
        _turn(9, "What would you admit is still unproven?", "The exact numbers may need internal validation but the impact was strong.", "synthesis_close", "AI revenue platform", "Claim calibration"),
    ]
    trap_scores = [
        _score(i + 1, score, turn["route_kind"], turn["focus_label"], turn["sub_focus_label"], turn["answer"], "high")
        for i, (turn, score) in enumerate(zip(trap_history, [3.8, 2.5, 3.0, 3.2, 3.1, 3.0, 3.6, 3.2, 3.0]))
    ]

    alternate_history = [
        _turn(1, "Tell me about the backend system you built.", "I supported API wiring, but my strongest work was the UI flow and product instrumentation around onboarding.", "warm_open", "SaaS platform", "Backend claim"),
        _turn(2, "How deep is your backend ownership?", "Moderate. I can write endpoints, but I am not strongest in distributed systems design.", "primary_depth", "SaaS platform", "Backend depth"),
        _turn(3, "What did you do well in the product/UI layer?", "I redesigned the onboarding flow, instrumented drop-offs, and improved completion using clearer error states and analytics.", "second_anchor", "Product UI", "UX instrumentation"),
        _turn(4, "Apply that to an enterprise activation problem.", "I would map the activation path, identify drop-offs, simplify the first successful action, and instrument role-specific completion events.", "application_transfer", "Product UI", "Application transfer"),
        _turn(5, "What risk remains for a backend-heavy role?", "I would need pairing on scaling and reliability design, but I can contribute strongly to product-facing systems.", "coverage_surface", "SaaS platform", "Role calibration"),
        _turn(6, "Where should a recruiter place you?", "A product engineer, UX-minded frontend engineer, or analytics-heavy growth role would fit better than pure backend infrastructure.", "synthesis_close", "Product UI", "Alternate fit"),
    ]
    alternate_scores = [
        _score(i + 1, score, turn["route_kind"], turn["focus_label"], turn["sub_focus_label"], turn["answer"], "medium" if i < 2 else "")
        for i, (turn, score) in enumerate(zip(alternate_history, [4.8, 5.0, 8.0, 7.8, 6.8, 7.5]))
    ]

    return {
        "best_product_strong": {
            "target_role": "Product Analyst",
            "years_experience": "1-2",
            "resume": "Product Analyst at Daily Mantra. Increased retention from 25% to 42%, optimized trial-to-subscription conversion from 27% to 42%, architected event tracking, and automated AppsFlyer dashboards.",
            "history": product_history,
            "per_answer_scores": product_scores,
            "weaknesses": [{"type": "causal_attribution", "severity": "low", "weakness": "Overlapping product launches require scoped attribution."}],
            "assessment_coverage": _coverage(),
            "coverage_map": _coverage_map(0.62),
            "expectations": {"not_no_hire": True, "coverage_passed": True, "alternate_fit": False},
        },
        "narrow_tunneled_product": {
            "target_role": "Product Analyst",
            "years_experience": "1-2",
            "resume": "Product Analyst at Daily Mantra with conversion, retention, event tracking, dashboard work, and a shorter CV research internship.",
            "history": tunneled_history,
            "per_answer_scores": tunneled_scores,
            "weaknesses": [{"type": "focus_mismatch", "severity": "high", "weakness": "Interview over-indexed on a less role-relevant CV internship."}],
            "assessment_coverage": _coverage(application_transfer_served=False, coverage_evaluated_dimensions=0, distinct_focuses=1, distinct_surfaces=1, high_value_surfaces_tested_count=0, dominant_focus_ratio=0.88, max_same_surface_streak=4, breadth_viable=False, full_breadth_viable=False, coverage_score=0.0, history_len=5),
            "coverage_map": _coverage_map(0.0, ["not_evaluated", "not_evaluated", "not_evaluated", "not_evaluated"]),
            "expectations": {"must_insufficient_data": True, "coverage_passed": False},
        },
        "honest_gap_corrected_overclaim": {
            "target_role": "Product Analyst",
            "years_experience": "1-2",
            "resume": "Architected zero-to-one analytics tracking and owned conversion funnel improvements.",
            "history": honest_history,
            "per_answer_scores": honest_scores,
            "weaknesses": [{"type": "ownership_scope", "severity": "medium", "weakness": "Resume verb overstated backend architecture ownership."}],
            "assessment_coverage": _coverage(coverage_score=0.50, distinct_surfaces=3),
            "coverage_map": _coverage_map(0.50, ["voluntary", "recovered_surface", "missed", "not_evaluated"]),
            "expectations": {"not_no_hire": True, "honesty_preserved": True, "coverage_passed": True},
        },
        "trap_inflated_claim": {
            "target_role": "AI Product Engineer",
            "years_experience": "3-5",
            "resume": "Architected AI RAG, OCR, dashboards, and revenue automation that increased revenue by 80%.",
            "history": trap_history,
            "per_answer_scores": trap_scores,
            "weaknesses": [
                {"type": "ownership", "severity": "high", "weakness": "Candidate could not define ownership boundaries."},
                {"type": "metric_denominator", "severity": "high", "weakness": "Candidate did not substantiate the 80% lift."},
            ],
            "assessment_coverage": _coverage(coverage_score=0.42, coverage_evaluated_dimensions=3, distinct_focuses=2, distinct_surfaces=4, dominant_focus_ratio=0.60),
            "coverage_map": _coverage_map(0.42, ["missed", "incorrect", "recovered_surface", "missed"]),
            "expectations": {"coverage_passed": True, "claim_risk_scoped": True},
        },
        "alternate_fit_product_ui": {
            "target_role": "Backend Software Engineer",
            "years_experience": "2-4",
            "resume": "Backend software engineer with UI onboarding, analytics instrumentation, and product experimentation experience.",
            "history": alternate_history,
            "per_answer_scores": alternate_scores,
            "weaknesses": [{"type": "role_depth", "severity": "medium", "weakness": "Backend depth weaker than product/UI signal."}],
            "assessment_coverage": _coverage(coverage_score=0.52, distinct_focuses=2, distinct_surfaces=3),
            "coverage_map": _coverage_map(0.52, ["recovered_surface", "voluntary", "missed", "not_evaluated"]),
            "expectations": {"not_no_hire": True, "alternate_fit": True, "coverage_passed": True},
        },
    }


def _text_blobs(report: dict[str, Any]) -> str:
    fields = [
        report.get("summary"),
        report.get("candidate_safe_summary"),
        report.get("recruiter_summary"),
        " ".join(str(item) for item in report.get("risk_flags") or []),
        " ".join(str(item) for item in report.get("tested_risks") or []),
    ]
    return "\n".join(str(item) for item in fields if item).lower()


def _evaluate_report(case: dict[str, Any], report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expectations = case.get("expectations") or {}
    coverage_gate = report.get("coverage_gate") if isinstance(report.get("coverage_gate"), dict) else {}
    recommendation = str(report.get("hire_recommendation") or "").upper().replace(" ", "_")
    text = _text_blobs(report)

    if report.get("schema_version") != "final_report_v2":
        failures.append("missing_final_report_v2_schema")
    for key in ("summary", "risk_flags", "strengths", "breakdown", "failure_surface"):
        if key not in report:
            failures.append(f"missing_legacy_field:{key}")
    if not isinstance(report.get("confidence_band"), dict):
        failures.append("missing_confidence_band")
    if not isinstance(report.get("interview_quality"), dict):
        failures.append("missing_interview_quality")
    if not isinstance(report.get("review_reconciliation"), dict):
        failures.append("missing_review_reconciliation")
    packet = report.get("final_evidence_packet") if isinstance(report.get("final_evidence_packet"), dict) else {}
    if not packet.get("turn_evidence_trail"):
        failures.append("missing_turn_evidence_trail")
    if not packet.get("progression_summary"):
        failures.append("missing_progression_summary")
    summary = str(report.get("candidate_safe_summary") or report.get("summary") or "").strip()
    summary_words = summary.split()
    if len(summary_words) < 18 or (summary_words and summary_words[-1].lower() in {"they", "and", "but", "while"}):
        failures.append("summary_looks_incomplete")

    if expectations.get("must_insufficient_data") and recommendation != "INSUFFICIENT_DATA":
        failures.append("coverage_gate_did_not_force_insufficient_data")
    if expectations.get("not_no_hire") and recommendation == "NO_HIRE":
        failures.append("unexpected_no_hire")
    if expectations.get("coverage_passed") is False and coverage_gate.get("passed") is not False:
        failures.append("coverage_gate_should_fail")
    if coverage_gate.get("passed") is False:
        if recommendation != "INSUFFICIENT_DATA":
            failures.append("failed_coverage_gate_without_insufficient_data")
        if any(term in text for term in ("fraud", "dishonest", "severe inability", "failed the interview")):
            failures.append("punitive_language_under_failed_coverage")
    if expectations.get("honesty_preserved"):
        human_lens = ((report.get("lens_findings") or {}).get("human_calibration_lens") or {})
        human_text = json.dumps(human_lens, ensure_ascii=True).lower()
        if not any(term in human_text for term in ("honest", "narrow", "clarif", "candid", "integrity", "calibrat")):
            failures.append("honest_correction_not_preserved")
        if any(term in text for term in ("fraud", "dishonest", "fabricated")):
            failures.append("honest_correction_punitive_language")
    if expectations.get("alternate_fit"):
        ability = report.get("ability_profile") if isinstance(report.get("ability_profile"), dict) else {}
        signal = str(ability.get("strongest_verified_signal") or "")
        archetypes = ability.get("alternate_fit_archetypes") or []
        if not signal and not archetypes:
            failures.append("alternate_fit_signal_missing")
    if expectations.get("claim_risk_scoped"):
        calibration = report.get("resume_claim_calibration") if isinstance(report.get("resume_claim_calibration"), dict) else {}
        claim_text = json.dumps(calibration, ensure_ascii=True).lower()
        if "scoped" not in claim_text and "claim" not in claim_text:
            failures.append("claim_risk_not_scoped_in_calibration")
    return failures


async def _run_one(model_key: str, model_id: str, case_key: str, case: dict[str, Any]) -> dict[str, Any]:
    agent = EvaluationAgent()
    agent.llm = LLMRouter(tier="large", model_override=model_id, timeout_override=180.0)
    started = time.perf_counter()
    row: dict[str, Any] = {
        "model_key": model_key,
        "model_id": model_id,
        "case_key": case_key,
        "ok": False,
    }
    try:
        report = await agent.score_full_interview(
            history=deepcopy(case["history"]),
            resume=case["resume"],
            weaknesses=deepcopy(case.get("weaknesses") or []),
            reasoning_signals=[],
            per_answer_scores=deepcopy(case.get("per_answer_scores") or []),
            coverage_map=deepcopy(case.get("coverage_map") or {}),
            assessment_coverage=deepcopy(case.get("assessment_coverage") or {}),
            target_role=case.get("target_role", ""),
            years_experience=case.get("years_experience", ""),
            parsed_resume={"source": "report_quality_matrix_fixture", "case_key": case_key},
        )
        failures = _evaluate_report(case, report)
        row.update({
            "ok": not failures,
            "failures": failures,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "hire_recommendation": report.get("hire_recommendation"),
            "overall_score": report.get("overall_score"),
            "confidence_score": report.get("confidence_score"),
            "coverage_gate_passed": (report.get("coverage_gate") or {}).get("passed"),
            "interview_quality_score": (report.get("interview_quality") or {}).get("score"),
            "confidence_band": report.get("confidence_band"),
            "review_concerns": len((report.get("review_reconciliation") or {}).get("reviewer_concerns") or []),
            "summary_excerpt": str(report.get("summary") or report.get("recruiter_summary") or "")[:500],
            "report": report,
        })
    except Exception as exc:
        row.update({
            "failures": ["exception"],
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        })
    return row


async def _run_matrix() -> dict[str, Any]:
    if not os.getenv("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not available in the loaded environment.")
    fixtures = _fixtures()
    selected_models = [
        item.strip()
        for item in os.getenv("REPORT_MATRIX_MODELS", ",".join(MODEL_CANDIDATES.keys())).split(",")
        if item.strip()
    ]
    selected_cases = [
        item.strip()
        for item in os.getenv("REPORT_MATRIX_CASES", ",".join(fixtures.keys())).split(",")
        if item.strip()
    ]
    rows: list[dict[str, Any]] = []
    for model_key in selected_models:
        model_id = MODEL_CANDIDATES.get(model_key, model_key)
        for case_key in selected_cases:
            if case_key not in fixtures:
                rows.append({
                    "model_key": model_key,
                    "model_id": model_id,
                    "case_key": case_key,
                    "ok": False,
                    "failures": ["unknown_case"],
                })
                continue
            print(f"[report-matrix] {model_key} / {case_key}", flush=True)
            rows.append(await _run_one(model_key, model_id, case_key, fixtures[case_key]))
    by_model: dict[str, Any] = {}
    for model_key in selected_models:
        model_rows = [row for row in rows if row["model_key"] == model_key]
        latencies = [float(row.get("latency_ms") or 0) for row in model_rows if row.get("latency_ms")]
        by_model[model_key] = {
            "model_id": MODEL_CANDIDATES.get(model_key, model_key),
            "cases": len(model_rows),
            "passes": sum(1 for row in model_rows if row.get("ok")),
            "failures": [row for row in model_rows if not row.get("ok")],
            "avg_latency_ms": round(mean(latencies), 1) if latencies else None,
        }
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": selected_models,
        "cases": selected_cases,
        "summary": {
            "total_cases": len(rows),
            "passes": sum(1 for row in rows if row.get("ok")),
            "failures": sum(1 for row in rows if not row.get("ok")),
            "all_green": all(row.get("ok") for row in rows),
        },
        "by_model": by_model,
        "rows": rows,
    }


def _md_table(rows: list[tuple[Any, ...]], headers: tuple[str, ...]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item).replace("\n", " ")[:240] for item in row) + " |")
    return lines


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Antigravity Report V2 Quality Matrix",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        *_md_table([
            ("Total model/case runs", report["summary"]["total_cases"]),
            ("Passes", report["summary"]["passes"]),
            ("Failures", report["summary"]["failures"]),
            ("All green", report["summary"]["all_green"]),
        ], ("Metric", "Value")),
        "",
        "## By Model",
        "",
    ]
    lines.extend(_md_table(
        [
            (
                model_key,
                data["model_id"],
                data["passes"],
                data["cases"],
                data["avg_latency_ms"],
            )
            for model_key, data in report["by_model"].items()
        ],
        ("Model", "OpenRouter ID", "Passes", "Cases", "Avg Latency ms"),
    ))
    lines.extend(["", "## Case Runs", ""])
    lines.extend(_md_table(
        [
            (
                row.get("model_key"),
                row.get("case_key"),
                row.get("ok"),
                row.get("hire_recommendation", ""),
                row.get("overall_score", ""),
                row.get("confidence_score", ""),
                row.get("coverage_gate_passed", ""),
                row.get("latency_ms", ""),
                row.get("failures", []),
                row.get("summary_excerpt", row.get("error", "")),
            )
            for row in report["rows"]
        ],
        ("Model", "Case", "OK", "Verdict", "Score", "Confidence", "Gate", "Latency", "Failures", "Excerpt"),
    ))
    lines.extend(["", "## Failure Details", ""])
    failures = [row for row in report["rows"] if not row.get("ok")]
    if not failures:
        lines.append("No failures.")
    else:
        for row in failures:
            lines.extend([
                f"### {row.get('model_key')} / {row.get('case_key')}",
                "",
                f"- Failures: `{row.get('failures')}`",
                f"- Error: `{row.get('error_type', '')} {row.get('error', '')}`",
                "",
            ])
    return "\n".join(lines) + "\n"


def main() -> None:
    output_prefix = Path(os.getenv("REPORT_MATRIX_OUT_PREFIX", "/tmp/antigravity_report_v2_quality_matrix"))
    report = asyncio.run(_run_matrix())
    json_path = output_prefix.with_suffix(".json")
    md_path = output_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    if not report["summary"]["all_green"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
