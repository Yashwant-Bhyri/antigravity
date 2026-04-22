"""
Validation checks for the strict interview-map preparation gate.

Run with:
  python3 -m backend.test_interview_map_validation
"""

from backend.services.interview_map import build_deterministic_interview_map, validate_interview_map
from backend.test_interview_map_contract import MESSY_RESUME


def main() -> None:
    deterministic_map = build_deterministic_interview_map(resume=MESSY_RESUME)
    strict_validation = validate_interview_map(deterministic_map, require_all_llm=True)

    assert not strict_validation["ready"], strict_validation
    assert strict_validation["errors"], strict_validation
    assert any("track_source is deterministic_fallback" in error for error in strict_validation["errors"]), strict_validation

    rich_map = build_deterministic_interview_map(resume=MESSY_RESUME)
    for area in rich_map["focus_areas"]:
        area["track_source"] = "llm"
        area["llm_branch_count"] = 18
        area["fallback_branch_count"] = 0
        area["llm_branches"] = [
            f"{sprint_key}.{branch}"
            for sprint_key in ("sprint_1", "sprint_2", "sprint_3")
            for branch in (
                "if_strong",
                "if_vague",
                "if_honest_gap",
                "if_claim_conflict",
                "if_short_answer",
                "bridge_to_next_focus",
            )
        ]
        area["fallback_branches"] = []
    rich_map["pending_hydration_focus_keys"] = []

    rich_validation = validate_interview_map(rich_map, require_all_llm=True)
    assert rich_validation["ready"], rich_validation
    assert rich_validation["llm_focus_count"] == len(rich_map["focus_areas"]), rich_validation

    print("interview-map validation checks passed")


if __name__ == "__main__":
    main()
