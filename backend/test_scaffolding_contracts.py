"""
No-credit checks for deterministic scaffolding around the live interview loop.

These tests cover model-adjacent consumers, state packets, coverage gates, and
cost-audit metadata. They do not call external LLM APIs.

Run with:
  PYTHONPATH=. python3 backend/test_scaffolding_contracts.py
"""

from __future__ import annotations

from backend.services.orchestrator import (
    _apply_hard_coverage_gate,
    _assessment_coverage,
    _build_question_packet,
    _clone_question_packet,
    _coverage_map_progress,
    _normalize_followups,
    _packet_followups_remaining,
)


def _assert_raises(fn, expected: str = "") -> None:
    try:
        fn()
    except Exception as exc:
        if expected and expected not in str(exc):
            raise AssertionError(f"Expected {expected!r} in {exc!r}") from exc
        return
    raise AssertionError("Expected function to raise.")


def test_question_packet_scaffolding_does_not_char_split() -> None:
    assert _normalize_followups("What is the denominator?") == []
    assert _normalize_followups([" Q1? ", "Q1?", "Q2?", 42], limit=3) == ["Q1?", "Q2?", "42"]

    packet = {
        "followups": "What is the denominator?",
        "asked_followup_count": "bad-int",
        "max_followups": "bad-int",
    }
    cloned = _clone_question_packet(packet)
    assert cloned["followups"] == []
    assert _packet_followups_remaining(packet) == []

    good_packet = {
        "followups": ["A?", "B?", "C?"],
        "asked_followup_count": "1",
        "max_followups": "2",
    }
    assert _packet_followups_remaining(good_packet) == ["B?"]


def test_map_backed_packet_requires_focus() -> None:
    _assert_raises(
        lambda: _build_question_packet(
            question_text="What moved that metric?",
            sprint=1,
            route_kind="trajectory_map_surface",
            parsed_resume={},
            resume="",
            focus_key_override="general",
        ),
        "missing map focus",
    )

    packet = _build_question_packet(
        question_text="What moved that metric?",
        sprint=1,
        route_kind="trajectory_map_surface",
        parsed_resume={},
        resume="",
        focus_key_override="conversion_lift",
        focus_label_override="Conversion lift",
        sub_focus_key_override="denominator",
    )
    assert packet["focus_key"] == "conversion_lift"
    assert packet["sub_focus_key"] == "denominator"


def test_coverage_progress_and_gate_tolerate_bad_shapes() -> None:
    progress = _coverage_map_progress({"coverage_score": "bad-float", "dimensions": "not-a-list"})
    assert progress == {
        "dimensions": 0,
        "evaluated": 0,
        "surfaced": 0,
        "unresolved": 0,
        "score": 0.0,
    }

    coverage = _assessment_coverage({
        "history": [
            {
                "question": "Q1",
                "answer": "This is a substantive answer with enough words to count as evidence.",
                "focus_key": "focus_a",
                "sub_focus_key": "surface_a",
            }
        ],
        "coverage_map": {"coverage_score": "bad-float", "dimensions": "not-a-list"},
        "interview_trajectory_map": {},
    })
    assert coverage["coverage_score"] == 0.0
    assert coverage["minimum_viable_completion"] is False

    gated = _apply_hard_coverage_gate(
        {"hire_recommendation": "NO HIRE", "overall_score": "bad-float", "confidence_score": "bad-float"},
        coverage,
    )
    assert gated["hire_recommendation"] == "INSUFFICIENT_DATA"
    assert gated["overall_score"] == 0.0
    assert gated["confidence_score"] == 0.45
    assert gated["coverage_gate"]["passed"] is False


def main() -> None:
    test_question_packet_scaffolding_does_not_char_split()
    test_map_backed_packet_requires_focus()
    test_coverage_progress_and_gate_tolerate_bad_shapes()
    print("scaffolding contract checks passed")


if __name__ == "__main__":
    main()
