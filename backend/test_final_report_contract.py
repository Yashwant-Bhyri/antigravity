import asyncio
import os

from backend.agents.evaluation_agent import EvaluationAgent
from backend.models.final_report import (
    build_interview_quality,
    build_final_evidence_packet,
    normalize_final_report_v2,
)


def _coverage(**overrides):
    base = {
        "application_transfer_served": True,
        "coverage_dimensions": 4,
        "coverage_evaluated_dimensions": 2,
        "coverage_surfaced_dimensions": 2,
        "coverage_score": 0.55,
        "distinct_focuses": 2,
        "distinct_surfaces": 2,
        "high_value_surfaces_available_count": 2,
        "high_value_surfaces_tested_count": 1,
        "dominant_focus_ratio": 0.50,
        "max_same_surface_streak": 3,
        "breadth_viable": True,
        "full_breadth_viable": True,
        "history_len": 15,
    }
    base.update(overrides)
    return base


def _history():
    return [
        {
            "question": "Your conversion improved from 27% to 42%; what moved that lift?",
            "answer": "I reduced the trial window, tracked trial starters as the denominator, and checked cancellation guardrails.",
            "focus_key": "daily_mantra",
            "focus_label": "Daily Mantra",
            "sub_focus_key": "conversion",
            "sub_focus_label": "Conversion experiment",
        },
        {
            "question": "How did the dashboard change decisions for campaign teams?",
            "answer": "It reconciled AppsFlyer spend with transactions daily, so teams could pause bad ad sets faster.",
            "focus_key": "dashboard",
            "focus_label": "Marketing dashboards",
            "sub_focus_key": "attribution",
            "sub_focus_label": "Attribution dashboard",
        },
    ]


def test_narrow_coverage_blocks_no_hire_and_harsh_language():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Architected event tracking and optimized conversion.",
        weaknesses=[{"type": "specificity", "severity": "high", "weakness": "Trial denominator was unclear."}],
        assessment_coverage=_coverage(
            distinct_focuses=1,
            distinct_surfaces=1,
            dominant_focus_ratio=0.9,
            max_same_surface_streak=6,
        ),
        target_role="Product Analyst",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "NO HIRE",
            "overall_score": 2,
            "confidence_score": 0.9,
            "summary": "The candidate showed severe inability and no demonstrable understanding.",
            "risk_flags": ["The candidate completely failed the interview."],
            "strengths": ["Some metric awareness."],
        },
        packet,
    )
    assert result["hire_recommendation"] == "INSUFFICIENT_DATA", result
    assert result["confidence_score"] <= 0.45, result
    assert "severe inability" not in result["summary"].lower(), result
    assert all("failed the interview" not in flag.lower() for flag in result["risk_flags"]), result


def test_resume_hype_is_scoped_claim_calibration_not_global_punishment():
    packet = build_final_evidence_packet(
        history=_history(),
        resume=(
            "Architected zero-to-one analytics event tracking. "
            "Optimized trial-to-subscription conversion from 27% to 42%."
        ),
        weaknesses=[{"type": "ownership", "severity": "medium", "weakness": "Architecture ownership needs follow-up."}],
        assessment_coverage=_coverage(),
        target_role="Product Analyst",
    )
    claims = packet["resume_claim_calibration"]["claims_tested"]
    assert claims, packet
    assert any(claim["hype_level"] in {"medium", "high"} for claim in claims), claims
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "MAYBE",
            "overall_score": 6,
            "confidence_score": 0.6,
            "risk_flags": ["Specific architecture ownership claim needs follow-up."],
            "strengths": ["Metric denominator and guardrail reasoning held up."],
        },
        packet,
    )
    assert result["resume_claim_calibration"]["impact_on_verdict"] == "scoped", result
    assert result["hire_recommendation"] == "MAYBE", result


def test_parent_focus_dominance_with_surface_breadth_is_not_tunneling():
    quality = build_interview_quality(
        _coverage(
            dominant_focus_ratio=0.86,
            distinct_focuses=1,
            distinct_surfaces=5,
            high_value_surfaces_tested_count=3,
            max_same_surface_streak=2,
        )
    )
    assert quality["tunneling_detected"] is False, quality
    assert "dominant_focus_ratio_high" not in quality["fairness_warnings"], quality
    assert "dominant_parent_focus_with_broad_surface_coverage" in quality["fairness_warnings"], quality


def test_incomplete_map_hydration_is_confidence_limit_not_candidate_risk():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Messy resume with seller activation, dashboards, checkout notes, and side projects.",
        weaknesses=[],
        assessment_coverage=_coverage(
            map_launch_ready=True,
            full_map_ready=False,
            needs_async_hydration=True,
            pending_hydration_focus_count=2,
            pending_hydration_focus_keys=["checkout_failure_funnel", "experiment_attribution"],
        ),
        target_role="Product Analytics Engineer",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "MAYBE",
            "overall_score": 6.5,
            "confidence_score": 0.65,
            "summary": "The candidate gave usable product analytics evidence, with some untested areas.",
        },
        packet,
    )
    assert result["coverage_gate"]["passed"] is True, result
    assert result["interview_quality"]["map_readiness"] == "launch_only", result
    assert "map_hydration_incomplete" in result["interview_quality"]["fairness_warnings"], result
    assert any("confidence limits" in flag for flag in result["risk_flags"]), result


def test_alternate_fit_signal_is_preserved():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Built dashboards and analytics workflows.",
        weaknesses=[],
        per_answer_scores=[{"score": 5.0}, {"score": 8.0}],
        assessment_coverage=_coverage(),
        target_role="Product Analyst",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "MAYBE",
            "overall_score": 6.5,
            "confidence_score": 0.65,
            "ability_profile": {
                "strongest_verified_signal": "Dashboard analytics and operator decision support were strong.",
                "alternate_fit_archetypes": ["analytics operations", "dashboard analytics"],
            },
        },
        packet,
    )
    assert "Dashboard analytics" in result["ability_profile"]["strongest_verified_signal"], result
    assert result["ability_profile"]["alternate_fit_archetypes"], result


def test_no_hire_with_high_score_and_alternate_fit_is_softened():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Backend engineer with product analytics and UI instrumentation work.",
        weaknesses=[{"type": "role_depth", "severity": "medium", "weakness": "Backend depth was weaker than product instrumentation."}],
        per_answer_scores=[{"score": 5.0}, {"score": 8.0}],
        assessment_coverage=_coverage(),
        target_role="Backend Software Engineer",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "NO HIRE",
            "overall_score": 6.5,
            "confidence_score": 0.9,
            "summary": "Strong adjacent product signal, but weak backend fit.",
            "ability_profile": {
                "strongest_verified_signal": "Product instrumentation was strong.",
                "alternate_fit_archetypes": ["Product Engineer"],
                "target_role_fit": "weak",
            },
        },
        packet,
        {"concerns": ["Score/verdict mismatch."]},
    )
    assert result["hire_recommendation"] == "MAYBE", result
    assert result["confidence_score"] <= 0.75, result
    assert result["review_reconciliation"]["accepted_changes"], result


def test_incomplete_summary_gets_evidence_fallback():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Built analytics dashboards.",
        weaknesses=[],
        per_answer_scores=[{"score": 7}, {"score": 8}],
        assessment_coverage=_coverage(),
        target_role="Product Analyst",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "HIRE",
            "overall_score": 7.0,
            "confidence_score": 0.7,
            "summary": "The candidate is strong. They",
        },
        packet,
    )
    assert len(result["summary"].split()) >= 18, result
    assert not result["summary"].endswith("They"), result


def test_poor_interviewer_quality_caps_no_hire():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Owned backend and UI work.",
        weaknesses=[],
        assessment_coverage=_coverage(
            application_transfer_served=False,
            coverage_evaluated_dimensions=0,
            distinct_focuses=1,
            distinct_surfaces=1,
            high_value_surfaces_tested_count=0,
        ),
        target_role="Software Engineer",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "NO HIRE",
            "overall_score": 3,
            "confidence_score": 0.8,
            "summary": "Narrow but concerning.",
        },
        packet,
    )
    assert result["interview_quality"]["score"] < 0.45, result
    assert result["hire_recommendation"] == "INSUFFICIENT_DATA", result
    assert result["coverage_gate"]["passed"] is False, result


def test_honest_correction_is_recorded_as_calibration_signal():
    history = _history() + [
        {
            "question": "Did you personally build the whole tracking system?",
            "answer": "I should clarify that I did not own the warehouse modeling, but I owned the event taxonomy and QA checks.",
            "focus_key": "daily_mantra",
            "sub_focus_key": "event_taxonomy",
        }
    ]
    packet = build_final_evidence_packet(
        history=history,
        resume="Owned analytics event tracking.",
        weaknesses=[],
        assessment_coverage=_coverage(distinct_surfaces=3),
        target_role="Product Analyst",
    )
    assert packet["honest_admissions"], packet
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "MAYBE",
            "overall_score": 6,
            "confidence_score": 0.6,
            "lens_findings": {
                "human_calibration_lens": {
                    "positive_signals": ["Candidate narrowed ownership instead of exaggerating."],
                    "negative_signals": [],
                    "inconclusive_signals": [],
                    "evidence_refs": [3],
                    "confidence": "medium",
                    "summary": "Honesty improved calibration.",
                }
            },
        },
        packet,
    )
    human_lens = result["lens_findings"]["human_calibration_lens"]
    assert human_lens["positive_signals"], result


def test_honest_correction_survives_missing_human_lens():
    history = _history() + [
        {
            "question": "Did you personally own all of it?",
            "answer": "I should clarify that I owned the event taxonomy and QA, not the SDK implementation.",
            "focus_key": "daily_mantra",
            "sub_focus_key": "event_taxonomy",
        }
    ]
    packet = build_final_evidence_packet(
        history=history,
        resume="Architected analytics tracking.",
        weaknesses=[],
        assessment_coverage=_coverage(distinct_surfaces=3),
        target_role="Product Analyst",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "HIRE",
            "overall_score": 7,
            "confidence_score": 0.7,
            "lens_findings": {"human_calibration_lens": {"positive_signals": [], "summary": ""}},
        },
        packet,
    )
    human_text = str(result["lens_findings"]["human_calibration_lens"]).lower()
    assert "clarif" in human_text or "honest" in human_text or "narrow" in human_text, result


def test_absence_of_honest_admission_is_not_standalone_risk():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Strong product analytics resume.",
        weaknesses=[],
        assessment_coverage=_coverage(distinct_surfaces=3),
        target_role="Product Analyst",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "MAYBE",
            "overall_score": 6.8,
            "confidence_score": 0.7,
            "risk_flags": [
                "MEDIUM: Zero honest admissions across 15 turns — no knowledge boundary acknowledged.",
                "MEDIUM: Guardrail thresholds need follow-up.",
            ],
        },
        packet,
    )
    joined = " ".join(result["risk_flags"]).lower()
    assert "zero honest admissions" not in joined, result
    assert "guardrail thresholds" in joined, result


def test_report_v2_keeps_legacy_fields():
    packet = build_final_evidence_packet(
        history=_history(),
        resume="Built analytics dashboards.",
        weaknesses=[],
        assessment_coverage=_coverage(),
        target_role="Product Analyst",
    )
    result = normalize_final_report_v2(
        {
            "hire_recommendation": "HIRE",
            "overall_score": 7.2,
            "confidence_score": 0.7,
            "breakdown": {"reasoning": 7, "technical_depth": 7, "communication": 8, "adaptability": 7},
            "failure_surface": {"product_analytics": 0.2},
            "summary": "Strong tested product analytics signal.",
            "risk_flags": [],
            "strengths": ["Clear metrics reasoning."],
        },
        packet,
    )
    for key in ("summary", "risk_flags", "strengths", "breakdown", "failure_surface", "claim_credibility_risk"):
        assert key in result, result
    assert result["schema_version"] == "final_report_v2", result


def test_turn_evidence_trail_models_progression_not_average_only():
    history = _history() + [
        {
            "question": "What guardrail changed your interpretation?",
            "answer": "I should clarify that cancellations were the guardrail; when refunds rose, we treated conversion lift as lower quality.",
            "focus_key": "daily_mantra",
            "focus_label": "Daily Mantra",
            "sub_focus_key": "guardrails",
            "sub_focus_label": "Experiment guardrails",
            "route_kind": "coverage_depth",
        }
    ]
    packet = build_final_evidence_packet(
        history=history,
        resume="Optimized conversion from 27% to 42%.",
        weaknesses=[],
        per_answer_scores=[
            {"turn_number": 1, "score": 4.0, "route_kind": "primary_depth", "focus_label": "Daily Mantra", "sub_focus_label": "Conversion experiment", "answer_excerpt": history[0]["answer"]},
            {"turn_number": 2, "score": 5.5, "route_kind": "second_anchor", "focus_label": "Marketing dashboards", "sub_focus_label": "Attribution dashboard", "answer_excerpt": history[1]["answer"]},
            {"turn_number": 3, "score": 7.2, "route_kind": "coverage_depth", "focus_label": "Daily Mantra", "sub_focus_label": "Experiment guardrails", "answer_excerpt": history[2]["answer"], "weakness_severity": "medium"},
        ],
        assessment_coverage=_coverage(distinct_surfaces=3),
        target_role="Product Analyst",
    )
    assert packet["avg_answer_score"] == 5.57, packet
    assert len(packet["turn_evidence_trail"]) == 3, packet
    assert packet["progression_summary"]["trajectory"] == "improved", packet
    assert packet["progression_summary"]["confidence_effect"] == "raises", packet
    assert any(item["recovery_signal"] for item in packet["turn_evidence_trail"]), packet


class _FakeRouter:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.model = "fake-model"

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_score_full_interview_uses_report_v2_and_explicit_token_budget():
    async def _run():
        agent = object.__new__(EvaluationAgent)
        agent.llm = _FakeRouter({
            "hire_recommendation": "HIRE",
            "overall_score": 7,
            "confidence_score": 0.7,
            "summary": "Strong role-relevant evidence.",
            "risk_flags": [],
            "strengths": ["Clear metric reasoning."],
        })
        agent.review_llm = _FakeRouter({"concerns": [], "tone_alignment": "fair"})
        previous = os.environ.get("REPORT_MAX_TOKENS")
        os.environ["REPORT_MAX_TOKENS"] = "5000"
        try:
            result = await agent.score_full_interview(
                history=_history(),
                resume="Built analytics dashboards.",
                weaknesses=[],
                per_answer_scores=[{"score": 7}, {"score": 8}],
                assessment_coverage=_coverage(),
                target_role="Product Analyst",
            )
        finally:
            if previous is None:
                os.environ.pop("REPORT_MAX_TOKENS", None)
            else:
                os.environ["REPORT_MAX_TOKENS"] = previous
        assert agent.llm.calls[0]["max_tokens"] == 5000
        assert result["schema_version"] == "final_report_v2", result
        assert "final_evidence_packet" in result, result

    asyncio.run(_run())


def main():
    test_narrow_coverage_blocks_no_hire_and_harsh_language()
    test_resume_hype_is_scoped_claim_calibration_not_global_punishment()
    test_parent_focus_dominance_with_surface_breadth_is_not_tunneling()
    test_incomplete_map_hydration_is_confidence_limit_not_candidate_risk()
    test_alternate_fit_signal_is_preserved()
    test_no_hire_with_high_score_and_alternate_fit_is_softened()
    test_incomplete_summary_gets_evidence_fallback()
    test_poor_interviewer_quality_caps_no_hire()
    test_honest_correction_is_recorded_as_calibration_signal()
    test_honest_correction_survives_missing_human_lens()
    test_absence_of_honest_admission_is_not_standalone_risk()
    test_report_v2_keeps_legacy_fields()
    test_turn_evidence_trail_models_progression_not_average_only()
    test_score_full_interview_uses_report_v2_and_explicit_token_budget()
    print("final report contract tests passed")


if __name__ == "__main__":
    main()
