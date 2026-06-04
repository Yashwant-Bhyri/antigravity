"""
Validation checks for the strict LLM-authored interview-map preparation gate.

Run with:
  python3 -m backend.test_interview_map_validation
"""

from backend.services.interview_map import validate_interview_map


def _llm_area(index: int) -> dict:
    dims = [
        {
            "id": f"focus_{index}_surface",
            "label": "Surface ownership",
            "intent": "Verify ownership",
            "surface": "What exact component did you personally own?",
            "mechanism": "How did that component work internally?",
            "boundary": "Where would that component fail under production load?",
            "strong_signal": "Specific mechanism and limits",
            "weak_signal": "Generic ownership claim",
            "signal_weight": 0.33,
        },
        {
            "id": f"focus_{index}_mechanism",
            "label": "Mechanism",
            "intent": "Probe causal depth",
            "surface": "Which design choice mattered most?",
            "mechanism": "Why did that choice improve the outcome?",
            "boundary": "What tradeoff did it introduce?",
            "strong_signal": "Causal explanation",
            "weak_signal": "Tool-name answer",
            "signal_weight": 0.34,
        },
        {
            "id": f"focus_{index}_boundary",
            "label": "Boundary",
            "intent": "Probe transfer",
            "surface": "What constraint shaped the implementation?",
            "mechanism": "How did you reason through that constraint?",
            "boundary": "What would you redesign first at 10x scale?",
            "strong_signal": "Transferable reasoning",
            "weak_signal": "No failure boundary",
            "signal_weight": 0.33,
        },
    ]
    return {
        "label": f"LLM Focus {index}",
        "focus_key": f"llm_focus_{index}",
        "track_source": "llm",
        "track_schema": "dimension",
        "llm_branch_count": len(dims),
        "fallback_branch_count": 0,
        "llm_branches": [dim["id"] for dim in dims],
        "fallback_branches": [],
        "question_ladder": [
            {
                "posture": "frame",
                "main_question": "What decision or problem made this focus area important enough to work on?",
                "signal_goal": "Frame the candidate's decision context.",
                "expected_space": ["decision", "problem", "scope"],
                "follow_up_if_shallow": "What made that problem important for users or the business?",
                "follow_up_if_strong": "What other option did you reject before choosing this direction?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "clarify",
                "main_question": "Which exact part did you own, and which part was owned by someone else?",
                "signal_goal": "Clarify ownership boundary.",
                "expected_space": ["owned work", "handoffs", "scope limit"],
                "follow_up_if_shallow": "What did you personally change or decide in that work?",
                "follow_up_if_strong": "Where did your ownership stop when another team became involved?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "explore",
                "main_question": "What changed in the user, system, or metric after your work went live?",
                "signal_goal": "Explore causal mechanism.",
                "expected_space": ["observed change", "evidence", "mechanism"],
                "follow_up_if_shallow": "What evidence told you that this change was real?",
                "follow_up_if_strong": "What other explanation did you try to rule out?",
                "information_gain": "high",
                "voice_complexity": "low",
            },
            {
                "posture": "pressure",
                "main_question": "If one important metric improved but quality dropped, what result would make you rethink the decision?",
                "signal_goal": "Pressure-test guardrail thinking.",
                "expected_space": ["guardrail", "threshold", "tradeoff"],
                "follow_up_if_shallow": "Which guardrail would matter most in that situation?",
                "follow_up_if_strong": "What threshold would make you stop or roll back the change?",
                "information_gain": "high",
                "voice_complexity": "medium",
            },
            {
                "posture": "synthesize",
                "main_question": "Which part of your conclusion are you most confident about, and which part is still uncertain?",
                "signal_goal": "Synthesize confidence and uncertainty.",
                "expected_space": ["confidence", "uncertainty", "evidence gap"],
                "follow_up_if_shallow": "What evidence supports the part you are most confident about?",
                "follow_up_if_strong": "What extra data would remove the remaining uncertainty?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
            {
                "posture": "recover",
                "main_question": "If you do not remember every detail, which part can you still explain clearly?",
                "signal_goal": "Recover signal from shallow answers.",
                "expected_space": ["known part", "ownership", "limits"],
                "follow_up_if_shallow": "What is the one part you personally remember doing?",
                "follow_up_if_strong": "Which part would you avoid claiming as your own?",
                "information_gain": "medium",
                "voice_complexity": "low",
            },
        ],
        "opener": "Walk me through the concrete system you built and the part you owned.",
        "dimensions": dims,
        "recovery": {
            "short_answer": "Which specific component are you referring to?",
            "honest_gap": "Which part can you still reason about confidently?",
            "claim_conflict": "What did you personally own versus inherit?",
            "metric_risk": "Which metric would fail first under pressure?",
            "overclaim_risk": "Where does your claim stop being true?",
            "bridge": "How does this connect to the next focus area?",
        },
    }


def main() -> None:
    invalid_map = {
        "focus_areas": [
            {
                **_llm_area(1),
                "track_source": "deterministic_fallback",
                "llm_branch_count": 0,
                "fallback_branch_count": 3,
            },
            _llm_area(2),
            _llm_area(3),
        ],
        "pending_hydration_focus_keys": [],
    }
    strict_validation = validate_interview_map(invalid_map, require_all_llm=True)

    assert not strict_validation["ready"], strict_validation
    assert strict_validation["errors"], strict_validation
    assert any("track_source is deterministic_fallback" in error for error in strict_validation["errors"]), strict_validation

    rich_map = {
        "focus_areas": [_llm_area(1), _llm_area(2), _llm_area(3)],
        "pending_hydration_focus_keys": [],
    }

    rich_validation = validate_interview_map(rich_map, require_all_llm=True)
    assert rich_validation["ready"], rich_validation
    assert rich_validation["llm_focus_count"] == len(rich_map["focus_areas"]), rich_validation

    print("interview-map validation checks passed")


if __name__ == "__main__":
    main()
