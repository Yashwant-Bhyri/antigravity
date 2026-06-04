from backend.agents.policy_checker_agent import PolicyCheckerAgent


def _turn(
    focus: str,
    sub_focus: str = "",
    route: str = "trajectory_map_surface",
    posture: str = "clarify",
    coverage_dim: str = "",
) -> dict:
    return {
        "focus_key": focus,
        "focus_label": focus.replace("_", " "),
        "sub_focus_key": sub_focus,
        "sub_focus_label": sub_focus.replace("_", " "),
        "route_kind": route,
        "question_posture": posture,
        "coverage_dimension_id": coverage_dim,
        "answer": "sample answer",
    }


def _packet(
    focus: str,
    sub_focus: str = "",
    route: str = "trajectory_map_surface",
    posture: str = "clarify",
    coverage_dim: str = "",
) -> dict:
    return {
        "question_text": "What was the decision you were trying to make?",
        "focus_key": focus,
        "focus_label": focus.replace("_", " "),
        "sub_focus_key": sub_focus,
        "sub_focus_label": sub_focus.replace("_", " "),
        "route_kind": route,
        "question_posture": posture,
        "coverage_dimension_id": coverage_dim,
    }


def _codes(result: dict) -> set[str]:
    return {warning["code"] for warning in result.get("warnings", [])}


def test_same_surface_streak_warns() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 4,
        "history": [_turn("retention", "trial") for _ in range(4)],
    }

    result = checker.check(
        state,
        next_packet=_packet("retention", "trial"),
        next_route_kind="trajectory_map_surface",
        turn_number=5,
    )

    assert result["policy_status"] == "block_recommended"
    assert "same_surface_streak" in _codes(result)


def test_same_parent_focus_with_distinct_surfaces_is_not_tunneling() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 5,
        "history": [
            _turn("daily_mantra", "trial_conversion"),
            _turn("daily_mantra", "guardrails"),
            _turn("daily_mantra", "event_taxonomy"),
            _turn("daily_mantra", route="coverage_surface", coverage_dim="denominator"),
            _turn("daily_mantra", route="coverage_surface", coverage_dim="causality"),
        ],
    }

    result = checker.check(
        state,
        next_packet=_packet("daily_mantra", route="coverage_surface", coverage_dim="retention"),
        next_route_kind="coverage_surface",
        turn_number=6,
    )

    assert "same_surface_streak" not in _codes(result)
    assert "same_parent_focus_low_surface_breadth" not in _codes(result)


def test_late_generic_route_warns() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 6,
        "history": [
            _turn("retention", "trial"),
            _turn("retention", "guardrails"),
            _turn("taxonomy", "events"),
            _turn("taxonomy", "dedupe"),
            _turn("dashboard", "attribution"),
            _turn("dashboard", "latency"),
        ],
    }

    result = checker.check(
        state,
        next_packet=_packet("retention", "trial", route="sprint_seed"),
        next_route_kind="sprint_seed",
        turn_number=7,
    )

    assert "late_generic_route" in _codes(result)


def test_grounded_legacy_route_label_is_low_noise_not_late_generic() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 8,
        "history": [
            _turn("activation", "denominator"),
            _turn("activation", "causality"),
            _turn("taxonomy", "ownership"),
            _turn("activation", route="coverage_surface", coverage_dim="guardrail"),
            _turn("dashboard", "decision_use"),
        ],
    }
    packet = _packet("dashboard", "reconciliation", route="legacy_agenda_backup", posture="explore")
    packet["question_text"] = "Which dashboard metric changed a real marketplace decision?"
    packet["question_quality"] = {
        "should_block": False,
        "flag_codes": [],
        "severity_counts": {"high": 0, "medium": 0, "low": 0},
    }

    result = checker.check(
        state,
        next_packet=packet,
        next_route_kind="legacy_agenda_backup",
        agenda_phase="primary_depth",
        agenda_reason="grounded_depth_continuation",
        turn_number=9,
    )

    assert "late_generic_route" not in _codes(result)
    assert "legacy_route_label" in _codes(result)


def test_application_transfer_missing_warns_after_evidence_window() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 7,
        "application_question_served": False,
        "history": [_turn("retention", f"surface_{idx}") for idx in range(7)],
    }

    result = checker.check(
        state,
        next_packet=_packet("dashboard", "attribution", route="second_anchor"),
        next_route_kind="second_anchor",
        turn_number=8,
    )

    assert "application_transfer_late_or_missing" in _codes(result)


def test_coverage_missing_after_application_warns() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 8,
        "application_question_served": True,
        "coverage_map": {
            "dimensions": [
                {"id": "denominator", "coverage_state": "not_evaluated"},
                {"id": "guardrail", "coverage_state": "not_evaluated"},
            ]
        },
        "history": [_turn("retention", f"surface_{idx}") for idx in range(8)],
    }

    result = checker.check(
        state,
        next_packet=_packet("dashboard", "attribution", route="second_anchor"),
        next_route_kind="second_anchor",
        turn_number=9,
    )

    assert "coverage_skipped_after_application" in _codes(result)


def test_pressure_posture_streak_warns() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 3,
        "history": [
            _turn("retention", "trial", posture="pressure"),
            _turn("retention", "guardrails", posture="pressure"),
        ],
    }

    result = checker.check(
        state,
        next_packet=_packet("retention", "denominator", posture="pressure"),
        next_route_kind="trajectory_map_surface",
        turn_number=3,
    )

    assert "prosecutor_streak" in _codes(result)


def test_map_backed_route_requires_focus() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 5,
        "history": [_turn("retention", f"surface_{idx}") for idx in range(5)],
    }

    result = checker.check(
        state,
        next_packet=_packet("", route="application_transfer"),
        next_route_kind="application_transfer",
        turn_number=6,
    )

    assert "map_focus_missing" in _codes(result)


def test_reserve_map_question_requires_focus() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 11,
        "application_question_served": True,
        "history": [_turn("retention", f"surface_{idx}") for idx in range(5)],
    }

    result = checker.check(
        state,
        next_packet=_packet("", route="reserve_map_question"),
        next_route_kind="reserve_map_question",
        turn_number=12,
    )

    assert "map_focus_missing" in _codes(result)


def test_synthesis_before_second_anchor_warns() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 10,
        "application_question_served": True,
        "history": [
            _turn("retention", "trial"),
            _turn("retention", "guardrails"),
            _turn("retention", route="coverage_surface", coverage_dim="denominator"),
            _turn("retention", route="coverage_surface", coverage_dim="sample_size"),
        ],
    }

    result = checker.check(
        state,
        next_packet=_packet("retention", route="synthesis_close"),
        next_route_kind="synthesis_close",
        turn_number=10,
    )

    assert "synthesis_before_second_anchor" in _codes(result)


def test_repeated_second_anchor_warns_as_holding_pattern() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 13,
        "application_question_served": True,
        "history": [
            _turn("retention", "trial"),
            _turn("retention", "guardrails"),
            _turn("retention", route="coverage_surface", coverage_dim="denominator"),
            _turn("dashboard", "attribution", route="second_anchor"),
            _turn("dashboard", "latency", route="second_anchor"),
            _turn("cv", "benchmarking", route="second_anchor"),
            _turn("cv", "tradeoffs", route="second_anchor"),
        ],
    }

    result = checker.check(
        state,
        next_packet=_packet("dashboard", "reconciliation", route="second_anchor"),
        next_route_kind="second_anchor",
        turn_number=14,
    )

    assert "second_anchor_overused" in _codes(result)


def test_fourth_second_anchor_warns_as_holding_pattern() -> None:
    checker = PolicyCheckerAgent()
    state = {
        "question_count": 11,
        "application_question_served": True,
        "history": [
            _turn("retention", route="coverage_surface", coverage_dim="denominator"),
            _turn("dashboard", "attribution", route="second_anchor"),
            _turn("dashboard", "latency", route="second_anchor"),
            _turn("cv", "benchmarking", route="second_anchor"),
        ],
    }

    result = checker.check(
        state,
        next_packet=_packet("cv", "tradeoffs", route="second_anchor"),
        next_route_kind="second_anchor",
        turn_number=13,
    )

    assert "second_anchor_overused" in _codes(result)


def test_bad_question_readiness_warns() -> None:
    checker = PolicyCheckerAgent()
    packet = _packet("dashboard", "ops", route="second_anchor", posture="synthesize")
    packet["question_text"] = "Which component are you most confident with?"
    packet["question_quality"] = {
        "should_block": True,
        "flag_codes": ["self_rating_certainty", "bad_synthesis_self_rating"],
        "severity_counts": {"high": 2, "medium": 0, "low": 0},
    }
    state = {
        "question_count": 12,
        "application_question_served": True,
        "history": [_turn("activation", "attribution") for _ in range(6)],
    }

    result = checker.check(
        state,
        next_packet=packet,
        next_route_kind="second_anchor",
        turn_number=13,
    )

    assert "bad_question_readiness" in _codes(result)


def test_nonblocking_question_readiness_warns_low() -> None:
    checker = PolicyCheckerAgent()
    packet = _packet("activation", "decision", route="trajectory_map_surface", posture="frame")
    packet["question_text"] = "When you changed the trial, were you testing conversion, urgency, or low-intent trials?"
    packet["question_quality"] = {
        "should_block": False,
        "flag_codes": ["closed_answer_lane_without_escape"],
        "severity_counts": {"high": 0, "medium": 1, "low": 0},
    }
    state = {"question_count": 2, "history": [_turn("activation", "decision")]}

    result = checker.check(
        state,
        next_packet=packet,
        next_route_kind="trajectory_map_surface",
        turn_number=2,
    )

    assert "question_readiness_warning" in _codes(result)


if __name__ == "__main__":
    test_same_surface_streak_warns()
    test_same_parent_focus_with_distinct_surfaces_is_not_tunneling()
    test_late_generic_route_warns()
    test_grounded_legacy_route_label_is_low_noise_not_late_generic()
    test_application_transfer_missing_warns_after_evidence_window()
    test_coverage_missing_after_application_warns()
    test_pressure_posture_streak_warns()
    test_map_backed_route_requires_focus()
    test_synthesis_before_second_anchor_warns()
    test_repeated_second_anchor_warns_as_holding_pattern()
    test_fourth_second_anchor_warns_as_holding_pattern()
    test_bad_question_readiness_warns()
    test_nonblocking_question_readiness_warns_low()
    print("policy checker contracts passed")
