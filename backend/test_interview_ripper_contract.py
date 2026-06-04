"""
No-credit end-to-end ripper contracts for interview orchestration.

These tests intentionally inject bad states instead of calling LLMs. The goal
is to answer: if map/app-transfer/coverage/question quality fails at turn 1-3
or around the application-transfer window, does the system fail closed, pivot,
or incorrectly keep drilling?

Run:
  PYTHONPATH=. python3 backend/test_interview_ripper_contract.py
"""

from __future__ import annotations

from backend.agents.policy_checker_agent import PolicyCheckerAgent
from backend.services.orchestrator import (
    _apply_hard_coverage_gate,
    _assessment_coverage,
    _build_question_packet,
    _select_agenda_decision,
    _select_reserve_question,
)
from backend.state.interview_agenda import initial_interview_agenda


def _interview_map(focus_count: int = 3) -> dict:
    focuses = [
        {
            "focus_key": "primary_product",
            "label": "Primary Product Analytics",
            "sub_focuses": [
                {"sub_focus_key": "conversion", "label": "Conversion", "coverage_value": 3.0},
                {"sub_focus_key": "guardrails", "label": "Guardrails", "coverage_value": 2.7},
            ],
            "question_ladder": [
                {
                    "posture": "frame",
                    "main_question": "When you changed the trial length, what business decision were you trying to make, and what else mattered?",
                    "signal_goal": "Frame the conversion decision without immediate pressure.",
                    "expected_space": ["conversion", "trial quality", "guardrails", "something else"],
                    "information_gain": "high",
                    "voice_complexity": "low",
                    "sub_focus_key": "conversion",
                    "sub_focus_label": "Conversion",
                },
                {
                    "posture": "clarify",
                    "main_question": "For the conversion lift, what denominator did you use, and did it include all users or only trial starters?",
                    "signal_goal": "Clarify denominator and measurement boundary.",
                    "expected_space": ["denominator", "cohort", "trial starters"],
                    "information_gain": "high",
                    "voice_complexity": "low",
                    "sub_focus_key": "guardrails",
                    "sub_focus_label": "Guardrails",
                },
            ],
        },
        {
            "focus_key": "dashboard_automation",
            "label": "Dashboard Automation",
            "sub_focuses": [
                {"sub_focus_key": "campaign_attribution", "label": "Campaign Attribution", "coverage_value": 2.4},
            ],
            "question_ladder": [
                {
                    "posture": "frame",
                    "main_question": "For the marketing dashboard, what decision did the team make faster because your reporting changed?",
                    "signal_goal": "Test dashboard impact without over-pressing the first turn.",
                    "expected_space": ["decision use", "refresh speed", "stakeholders"],
                    "information_gain": "high",
                    "voice_complexity": "low",
                    "sub_focus_key": "campaign_attribution",
                    "sub_focus_label": "Campaign Attribution",
                }
            ],
        },
        {
            "focus_key": "cv_benchmark",
            "label": "Computer Vision Benchmarking",
            "sub_focuses": [
                {"sub_focus_key": "benchmark_tradeoffs", "label": "Benchmark Tradeoffs", "coverage_value": 1.2},
            ],
        },
    ]
    return {"focus_areas": focuses[:focus_count]}


def _state(focus_count: int = 3) -> dict:
    interview_map = _interview_map(focus_count)
    return {
        "interview_trajectory_map": interview_map,
        "interview_agenda": initial_interview_agenda(interview_map),
        "candidate_state": {"implementation_anchor": "I owned the Daily Mantra experiment analysis."},
        "history": [],
        "question_count": 0,
        "evidence_question_count": 0,
        "application_question_served": False,
        "prepped_application_question": "",
    }


def _turn(
    focus: str = "primary_product",
    sub_focus: str = "conversion",
    route: str = "trajectory_map_surface",
    coverage_dim: str = "",
) -> dict:
    return {
        "focus_key": focus,
        "focus_label": focus.replace("_", " "),
        "sub_focus_key": sub_focus,
        "sub_focus_label": sub_focus.replace("_", " "),
        "route_kind": route,
        "coverage_dimension_id": coverage_dim,
        "answer": "sample answer",
    }


def _decision(state: dict, *, history: list[dict], route: str = "trajectory_map_surface", focus: str = "primary_product") -> dict:
    return _select_agenda_decision(
        state,
        history=history,
        current_focus_key=focus,
        current_focus_label=focus.replace("_", " "),
        answered_route_kind=route,
        weakness={"severity": "high", "continue_probing": True},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )


def test_turn_one_two_three_bad_primary_answers_do_not_force_early_off_role_pivot() -> None:
    """Early weak answers should not trigger the old ratio-math CV jump."""
    state = _state()
    for turn_count in (1, 2):
        history = [_turn(sub_focus=f"surface_{idx}") for idx in range(turn_count)]
        state["evidence_question_count"] = turn_count
        decision = _decision(state, history=history)
        assert decision["route"] == "phase_depth", decision
        assert decision["focus_key"] == "primary_product", decision


def test_repeated_weak_primary_answers_pivot_after_primary_floor() -> None:
    state = _state()
    state["evidence_question_count"] = 4
    history = [_turn(sub_focus="same_surface") for _ in range(4)]
    decision = _select_agenda_decision(
        state,
        history=history,
        current_focus_key="primary_product",
        current_focus_label="Primary Product Analytics",
        answered_route_kind="trajectory_map_surface",
        weakness={"severity": "high", "continue_probing": False},
        discrepancy_conflict=False,
        honest_admission=False,
        force_focus_rotation=False,
    )
    assert decision["route"] == "focus_pivot", decision
    assert decision["focus_key"] == "dashboard_automation", decision


def test_application_transfer_missing_at_deadline_blocks_instead_of_generic_escape() -> None:
    state = _state()
    state["candidate_state"] = {}
    state["evidence_question_count"] = 5
    state["prepped_application_question"] = ""
    history = [_turn(sub_focus=f"surface_{idx}") for idx in range(5)]
    decision = _decision(state, history=history)
    assert decision["route"] == "application_anchor_recovery", decision
    assert decision["reason"] == "application_anchor_recovery_needed", decision


def test_application_anchor_recovery_gets_one_chance_before_resume_fallback_block() -> None:
    state = _state()
    state["candidate_state"] = {}
    state["evidence_question_count"] = 6
    state["prepped_application_question"] = ""
    state["application_anchor_recovery_served"] = True
    history = [_turn(sub_focus=f"surface_{idx}") for idx in range(5)]
    decision = _decision(state, history=history, route="application_anchor_recovery")
    assert decision["route"] == "application_transfer_blocked", decision
    assert decision["reason"] == "application_transfer_required_but_not_ready", decision


def test_application_transfer_ready_beats_high_weakness_drill() -> None:
    state = _state()
    state["evidence_question_count"] = 4
    state["prepped_application_question"] = "How would you apply this analytics decision to a new subscription flow?"
    history = [_turn(sub_focus=f"surface_{idx}") for idx in range(4)]
    decision = _decision(state, history=history)
    assert decision["route"] == "application_transfer", decision


def test_application_transfer_answer_forces_coverage_even_when_weakness_is_high() -> None:
    state = _state()
    state["application_question_served"] = True
    state["coverage_map"] = {
        "coverage_score": 0.0,
        "dimensions": [
            {"id": "denominator", "coverage_state": "not_evaluated", "surfacing_attempted": False},
            {"id": "guardrail", "coverage_state": "not_evaluated", "surfacing_attempted": False},
        ],
    }
    decision = _decision(state, history=[_turn() for _ in range(5)], route="application_transfer")
    assert decision["route"] == "coverage", decision
    assert decision["reason"] == "application_answer_requires_coverage", decision


def test_application_transfer_requires_two_evaluated_dimensions_when_available() -> None:
    state = _state()
    state["application_question_served"] = True
    state["history"] = [
        _turn("primary_product", "conversion"),
        _turn("primary_product", route="coverage_surface", coverage_dim="denominator"),
        _turn("dashboard_automation", "campaign_attribution", route="second_anchor"),
    ]
    state["coverage_map"] = {
        "coverage_score": 0.5,
        "dimensions": [
            {"id": "denominator", "coverage_state": "voluntary", "surfacing_attempted": True},
            {"id": "guardrail", "coverage_state": "not_evaluated", "surfacing_attempted": False},
            {"id": "confound", "coverage_state": "not_evaluated", "surfacing_attempted": False},
        ],
    }
    coverage = _assessment_coverage(state)
    assert coverage["coverage_min_evaluated_dimensions"] == 2, coverage
    assert coverage["minimum_viable_completion"] is False, coverage
    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "HIRE", "overall_score": 8.2, "confidence_score": 0.8},
        coverage,
    )
    assert gated["hire_recommendation"] == "INSUFFICIENT_DATA", gated
    assert "coverage_dimensions_not_evaluated" in gated["coverage_gate"]["reasons"], gated


def test_earned_application_depth_probe_caps_full_completion_until_served() -> None:
    state = _state()
    state["application_question_served"] = True
    state["question_count"] = 15
    state["evidence_question_count"] = 15
    state["history"] = [
        _turn("primary_product", "conversion"),
        _turn("primary_product", route="coverage_surface", coverage_dim="denominator"),
        _turn("dashboard_automation", "campaign_attribution", route="second_anchor"),
    ]
    state["coverage_map"] = {
        "coverage_score": 0.7,
        "dimensions": [
            {"id": "denominator", "coverage_state": "voluntary", "surfacing_attempted": True, "depth_eligible": True, "weight": 3.0},
            {"id": "guardrail", "coverage_state": "voluntary", "surfacing_attempted": True, "depth_eligible": False, "weight": 2.4},
        ],
    }
    coverage = _assessment_coverage(state)
    assert coverage["coverage_depth_probe_available"] is True, coverage
    assert coverage["full_completion_eligible"] is False, coverage
    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "HIRE", "overall_score": 8.2, "confidence_score": 0.8},
        coverage,
    )
    assert "application_transfer_depth_probe_not_served" in gated["coverage_gate"]["reasons"], gated


def test_empty_coverage_map_can_continue_conversation_but_final_verdict_is_gated() -> None:
    state = _state(focus_count=2)
    state["application_question_served"] = True
    state["coverage_map"] = {"coverage_score": 0, "dimensions": []}
    state["evidence_question_count"] = 10
    state["question_count"] = 10
    history = [
        _turn("primary_product", "conversion"),
        _turn("primary_product", "guardrails"),
        _turn("primary_product", route="application_transfer"),
    ]
    decision = _decision(state, history=history, route="application_transfer")
    assert decision["route"] == "coverage", decision

    decision = _decision(
        state,
        history=history + [_turn("primary_product", route="coverage_surface")],
        route="coverage_surface",
    )
    assert decision["route"] == "phase_depth", decision

    state["history"] = history + [_turn("dashboard_automation", "campaign_attribution", route="second_anchor")]
    coverage = _assessment_coverage(state)
    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "HIRE", "overall_score": 8.2, "confidence_score": 0.8},
        coverage,
    )
    assert gated["hire_recommendation"] == "INSUFFICIENT_DATA", gated
    assert "coverage_dimensions_not_evaluated" in gated["coverage_gate"]["reasons"], gated


def test_coverage_complete_before_visible_floor_does_not_start_second_anchor() -> None:
    state = _state(focus_count=2)
    state["application_question_served"] = True
    state["coverage_map"] = {
        "coverage_score": 0.7,
        "dimensions": [
            {"id": "denominator", "coverage_state": "voluntary", "surfacing_attempted": True},
            {"id": "guardrail", "coverage_state": "missed", "surfacing_attempted": True},
        ],
    }
    state["question_count"] = 7
    state["evidence_question_count"] = 10
    history = [
        _turn("primary_product", "conversion"),
        _turn("primary_product", "guardrails"),
        _turn("primary_product", route="application_transfer"),
        _turn("primary_product", route="coverage_surface", coverage_dim="denominator"),
        _turn("primary_product", route="coverage_surface", coverage_dim="guardrail"),
    ]
    decision = _decision(state, history=history, route="coverage_surface")
    assert decision["route"] == "phase_depth", decision
    assert decision["reason"] == "second_anchor_wait_until_floor", decision


def test_two_anchor_map_escapes_to_second_anchor_then_synthesis_budget() -> None:
    state = _state(focus_count=2)
    state["application_question_served"] = True
    state["coverage_map"] = {
        "coverage_score": 0.7,
        "dimensions": [
            {"id": "denominator", "coverage_state": "voluntary", "surfacing_attempted": True},
            {"id": "guardrail", "coverage_state": "missed", "surfacing_attempted": True},
        ],
    }
    state["evidence_question_count"] = 10
    state["question_count"] = 9
    history = [
        _turn("primary_product", "conversion"),
        _turn("primary_product", "guardrails"),
        _turn("primary_product", route="application_transfer"),
        _turn("primary_product", route="coverage_surface", coverage_dim="denominator"),
        _turn("primary_product", route="coverage_surface", coverage_dim="guardrail"),
        _turn("primary_product", "guardrails", route="trajectory_map_boundary"),
        _turn("primary_product", "conversion", route="trajectory_map_boundary"),
        _turn("primary_product", "guardrails", route="trajectory_map_boundary"),
        _turn("primary_product", "conversion", route="trajectory_map_boundary"),
    ]
    decision = _decision(state, history=history, route="coverage_surface")
    assert decision["route"] == "second_anchor", decision
    assert decision["focus_key"] == "dashboard_automation", decision

    state["evidence_question_count"] = 12
    state["question_count"] = 12
    exhausted_history = history + [
        _turn("dashboard_automation", "campaign_attribution", route="second_anchor"),
        _turn("dashboard_automation", "campaign_attribution", route="second_anchor"),
        _turn("dashboard_automation", "campaign_attribution", route="second_anchor"),
    ]
    decision = _decision(state, history=exhausted_history, route="second_anchor", focus="dashboard_automation")
    assert decision["route"] == "synthesis_close", decision


def test_map_backed_bad_question_without_focus_fails_packet_construction() -> None:
    try:
        _build_question_packet(
            question_text="How would you apply this to a new subscription flow?",
            sprint=1,
            route_kind="application_transfer",
            parsed_resume={},
            resume="",
        )
    except RuntimeError as exc:
        assert "missing map focus attribution" in str(exc)
    else:
        raise AssertionError("map-backed packet without focus should fail closed")


def test_reserve_question_prefers_unasked_coverage_dimension() -> None:
    state = _state()
    state["application_question_served"] = True
    state["application_transfer_fallback_focus_key"] = "primary_product"
    state["application_transfer_fallback_focus_label"] = "Primary Product Analytics"
    state["coverage_map"] = {
        "dimensions": [
            {
                "id": "denominator",
                "label": "Denominator",
                "weight": 2.8,
                "description": "Check metric boundary.",
                "surfacing_question": "For the 42% conversion metric, what exactly was in the denominator?",
                "expected_approaches": ["all eligible users", "trial starters", "exclusions"],
            },
            {
                "id": "guardrail",
                "label": "Guardrail",
                "weight": 2.4,
                "description": "Check negative side effects.",
                "surfacing_question": "What guardrail would make you rethink the one-day trial change?",
                "expected_approaches": ["refunds", "retention", "support complaints"],
            },
        ]
    }

    result = _select_reserve_question(state, [_turn("primary_product", "conversion")])

    assert result, result
    assert result["route_kind"] == "coverage_surface", result
    assert result["focus_key"] == "primary_product", result
    assert result["coverage_dimension_id"] == "denominator", result
    assert result["reason"] == "reserve_unasked_coverage_dimension", result


def test_reserve_question_falls_back_to_unasked_ladder_surface() -> None:
    state = _state()
    state["coverage_map"] = {"dimensions": []}
    history = [
        {
            **_turn("primary_product", "conversion"),
            "question": "When you changed the trial length, what business decision were you trying to make, and what else mattered?",
        }
    ]

    result = _select_reserve_question(state, history)

    assert result, result
    assert result["route_kind"] == "reserve_map_question", result
    assert result["focus_key"] == "primary_product", result
    assert result["sub_focus_key"] == "guardrails", result
    assert "denominator" in result["question"].lower(), result
    assert result["reason"] == "reserve_unasked_ladder_question", result


def test_reserve_question_avoids_current_focus_when_other_map_surface_exists() -> None:
    state = _state()
    state["coverage_map"] = {"dimensions": []}
    history = [
        {
            **_turn("primary_product", "conversion"),
            "question": "When you changed the trial length, what business decision were you trying to make, and what else mattered?",
        },
        {
            **_turn("primary_product", "guardrails"),
            "question": "For the conversion lift, what denominator did you use, and did it include all users or only trial starters?",
        },
    ]

    result = _select_reserve_question(state, history, avoid_focus="primary_product")

    assert result, result
    assert result["route_kind"] == "reserve_map_question", result
    assert result["focus_key"] == "dashboard_automation", result
    assert result["sub_focus_key"] == "campaign_attribution", result


def test_policy_checker_flags_bad_escape_routes_but_does_not_steer_yet() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 8,
        "application_question_served": False,
        "history": [_turn(sub_focus=f"surface_{idx}") for idx in range(8)],
    }
    result = checker.check(
        state,
        next_packet={
            "question_text": "Tell me about another project.",
            "route_kind": "sprint_seed",
            "focus_key": "dashboard_automation",
            "focus_label": "Dashboard Automation",
        },
        next_route_kind="sprint_seed",
        turn_number=9,
    )
    codes = {warning["code"] for warning in result.get("warnings", [])}
    assert "late_generic_route" in codes, result
    assert "application_transfer_late_or_missing" in codes, result
    assert result["should_steer"] is False, result


def test_tunneled_broad_rejection_is_downgraded_to_insufficient_data() -> None:
    state = _state()
    state["application_question_served"] = True
    state["coverage_map"] = {
        "coverage_score": 0.2,
        "dimensions": [{"id": "denominator", "coverage_state": "missed", "surfacing_attempted": True}],
    }
    state["history"] = [_turn("primary_product", "same_surface") for _ in range(6)]
    coverage = _assessment_coverage(state)
    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "NO HIRE", "overall_score": 2.5, "confidence_score": 0.9},
        coverage,
    )
    assert gated["hire_recommendation"] == "INSUFFICIENT_DATA", gated
    reasons = set(gated["coverage_gate"]["reasons"])
    assert "same_surface_streak_exceeded" in reasons, gated
    assert "interview_tunneled_on_one_focus" in reasons, gated


def main() -> None:
    test_turn_one_two_three_bad_primary_answers_do_not_force_early_off_role_pivot()
    test_repeated_weak_primary_answers_pivot_after_primary_floor()
    test_application_transfer_missing_at_deadline_blocks_instead_of_generic_escape()
    test_application_anchor_recovery_gets_one_chance_before_resume_fallback_block()
    test_application_transfer_ready_beats_high_weakness_drill()
    test_application_transfer_answer_forces_coverage_even_when_weakness_is_high()
    test_application_transfer_requires_two_evaluated_dimensions_when_available()
    test_earned_application_depth_probe_caps_full_completion_until_served()
    test_empty_coverage_map_can_continue_conversation_but_final_verdict_is_gated()
    test_coverage_complete_before_visible_floor_does_not_start_second_anchor()
    test_two_anchor_map_escapes_to_second_anchor_then_synthesis_budget()
    test_map_backed_bad_question_without_focus_fails_packet_construction()
    test_reserve_question_prefers_unasked_coverage_dimension()
    test_reserve_question_falls_back_to_unasked_ladder_surface()
    test_reserve_question_avoids_current_focus_when_other_map_surface_exists()
    test_policy_checker_flags_bad_escape_routes_but_does_not_steer_yet()
    test_tunneled_broad_rejection_is_downgraded_to_insufficient_data()
    print("interview ripper contract tests passed")


if __name__ == "__main__":
    main()
