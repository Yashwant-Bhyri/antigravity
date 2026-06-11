from backend.services.question_quality import check_question_readiness
from backend.test_robust_interview_simulation_suite import RobustCase, _best_worst_questions


def _codes(result: dict) -> set[str]:
    return set(result.get("flag_codes") or [])


def test_self_rating_variants_are_blocked() -> None:
    result = check_question_readiness(
        "Which component are you most confident with?",
        route_kind="second_anchor",
        posture="synthesize",
        turn_number=13,
        expected_space=["evidence"],
    )

    assert result["should_block"] is True
    assert "self_rating_certainty" in _codes(result)
    assert "bad_synthesis_self_rating" in _codes(result)


def test_low_signal_sql_recall_is_blocked_late() -> None:
    result = check_question_readiness(
        "What specific SQL script or query structure did you reuse to audit these volumes?",
        route_kind="coverage_depth_probe",
        posture="recover",
        turn_number=12,
        expected_space=["segmentation", "confound check"],
    )

    assert result["should_block"] is True
    assert "low_signal_implementation_recall" in _codes(result)
    assert "late_low_level_probe" in _codes(result)


def test_tool_recall_is_blocked_as_low_signal() -> None:
    result = check_question_readiness(
        "What was the main tool you used most for this work?",
        route_kind="third_surface_probe",
        posture="recover",
        turn_number=12,
        expected_space=["dashboard decision use"],
    )

    assert result["should_block"] is True
    assert "low_signal_implementation_recall" in _codes(result)
    assert "late_low_level_probe" in _codes(result)


def test_plural_tool_recall_is_blocked_as_low_signal() -> None:
    result = check_question_readiness(
        "What tools did you use to pull and validate the funnel data?",
        route_kind="trajectory_map_followup",
        posture="recover",
        turn_number=5,
        expected_space=["data validation reasoning"],
    )

    assert result["should_block"] is True
    assert "low_signal_implementation_recall" in _codes(result)


def test_file_format_recall_is_blocked_as_low_signal() -> None:
    result = check_question_readiness(
        "What file format did your telemetry use to store that payload?",
        route_kind="trajectory_map_mechanism",
        posture="recover",
        turn_number=12,
        expected_space=["telemetry reasoning"],
    )

    assert result["should_block"] is True
    assert "low_signal_implementation_recall" in _codes(result)
    assert "late_low_level_probe" in _codes(result)


def test_team_deployment_recall_is_blocked_as_low_signal() -> None:
    result = check_question_readiness(
        "Which team owned production dbt deployments?",
        route_kind="third_surface_probe",
        posture="recover",
        turn_number=11,
        expected_space=["ownership boundary"],
    )

    assert result["should_block"] is True
    assert "low_signal_ownership_recall" in _codes(result)
    assert "late_low_level_probe" in _codes(result)


def test_ownership_boundary_question_is_still_allowed() -> None:
    result = check_question_readiness(
        "Which part did you personally own, and where did engineering take over?",
        route_kind="trajectory_map_followup",
        posture="clarify",
        turn_number=4,
        expected_space=["candidate boundary", "engineering boundary"],
    )

    assert result["should_block"] is False
    assert "low_signal_ownership_recall" not in _codes(result)


def test_guided_answer_lane_with_escape_hatch_is_allowed() -> None:
    result = check_question_readiness(
        "When you moved the trial from 7 days to 1 day, were you mainly trying to improve conversion, reduce low-intent trials, test urgency, or was there something else?",
        route_kind="trajectory_map_surface",
        posture="frame",
        turn_number=2,
        expected_space=["conversion", "trial quality", "urgency", "other reason"],
    )

    assert result["should_block"] is False
    assert "closed_answer_lane_without_escape" not in _codes(result)


def test_guided_answer_lane_without_escape_is_warned() -> None:
    result = check_question_readiness(
        "When you moved the trial from 7 days to 1 day, were you mainly trying to improve conversion, reduce low-intent trials, or test urgency?",
        route_kind="trajectory_map_surface",
        posture="frame",
        turn_number=2,
        expected_space=["conversion", "trial quality", "urgency"],
    )

    assert result["should_block"] is False
    assert "closed_answer_lane_without_escape" in _codes(result)


def test_unsupported_internals_are_warned_not_blindly_accepted() -> None:
    result = check_question_readiness(
        "When you changed the video workflow, how did you modify the model weights?",
        route_kind="application_transfer",
        posture="pressure",
        turn_number=7,
        expected_space=["system boundary"],
    )

    assert "possible_unsupported_internals" in _codes(result)


def test_terminal_messages_are_not_ranked_as_bad_questions() -> None:
    case = RobustCase(
        key="terminal_scoring",
        label="Terminal scoring",
        purpose="Question quality contract",
        resume="",
        target_role="Product Analyst",
        years_experience="2",
        answer_profile={},
        expected_anchors=["activation"],
        expected_failure_probes=["guardrail"],
    )
    result = _best_worst_questions(
        [
            {
                "turn": 1,
                "route_kind": "trajectory_map_surface",
                "state_focus_label": "Activation",
                "ai_response": "What guardrail would show the activation lift was unhealthy?",
            },
            {
                "turn": 15,
                "route_kind": "complete",
                "state_focus_label": "Activation",
                "ai_response": "That wraps up our interview. Your report is being generated now.",
            },
        ],
        case,
    )

    ranked_questions = [item["question"] for side in result.values() for item in side]
    assert all("wraps up" not in question.lower() for question in ranked_questions)


def main() -> None:
    test_self_rating_variants_are_blocked()
    test_low_signal_sql_recall_is_blocked_late()
    test_tool_recall_is_blocked_as_low_signal()
    test_plural_tool_recall_is_blocked_as_low_signal()
    test_file_format_recall_is_blocked_as_low_signal()
    test_team_deployment_recall_is_blocked_as_low_signal()
    test_ownership_boundary_question_is_still_allowed()
    test_guided_answer_lane_with_escape_hatch_is_allowed()
    test_guided_answer_lane_without_escape_is_warned()
    test_unsupported_internals_are_warned_not_blindly_accepted()
    test_terminal_messages_are_not_ranked_as_bad_questions()
    print("question quality contracts passed")


if __name__ == "__main__":
    main()
