from __future__ import annotations

from dataclasses import dataclass, field


DISENGAGEMENT_INCREMENTS: dict[str, float] = {
    "explicit_skip": 2.0,
    "social_deflection": 1.0,
    "zero_content": 0.5,
    "incoherent": 1.0,
    "substantive_answer": -0.5,
}


@dataclass
class CandidateState:
    disengagement_level: float = 0.0
    consecutive_no_content: int = 0
    explicit_skip_count: int = 0
    social_deflection_count: int = 0
    incoherence_count: int = 0
    communication_mode: str = "normal"
    topic_fatigue: dict[str, int] = field(default_factory=dict)
    topic_question_counts: dict[str, int] = field(default_factory=dict)
    topic_fatigue_threshold: int = 4
    forced_exit_triggered: bool = False
    phase: str = "orientation"
    anchor_confidence: str | None = None
    implementation_anchor: str | None = None
    second_domain_surfaced: str | None = None
    save_face_pivot_used: bool = False

    def to_dict(self) -> dict:
        return {
            "disengagement_level": self.disengagement_level,
            "consecutive_no_content": self.consecutive_no_content,
            "explicit_skip_count": self.explicit_skip_count,
            "social_deflection_count": self.social_deflection_count,
            "incoherence_count": self.incoherence_count,
            "communication_mode": self.communication_mode,
            "topic_fatigue": dict(self.topic_fatigue),
            "topic_question_counts": dict(self.topic_question_counts),
            "topic_fatigue_threshold": self.topic_fatigue_threshold,
            "forced_exit_triggered": self.forced_exit_triggered,
            "phase": self.phase,
            "anchor_confidence": self.anchor_confidence,
            "implementation_anchor": self.implementation_anchor,
            "second_domain_surfaced": self.second_domain_surfaced,
            "_save_face_pivot_used": self.save_face_pivot_used,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateState":
        return cls(
            disengagement_level=float(data.get("disengagement_level", 0.0)),
            consecutive_no_content=int(data.get("consecutive_no_content", 0)),
            explicit_skip_count=int(data.get("explicit_skip_count", 0)),
            social_deflection_count=int(data.get("social_deflection_count", 0)),
            incoherence_count=int(data.get("incoherence_count", 0)),
            communication_mode=str(data.get("communication_mode", "normal")),
            topic_fatigue=dict(data.get("topic_fatigue", {})),
            topic_question_counts=dict(data.get("topic_question_counts", {})),
            topic_fatigue_threshold=int(data.get("topic_fatigue_threshold", 4)),
            forced_exit_triggered=bool(data.get("forced_exit_triggered", False)),
            phase=str(data.get("phase", "orientation")),
            anchor_confidence=data.get("anchor_confidence"),
            implementation_anchor=data.get("implementation_anchor"),
            second_domain_surfaced=data.get("second_domain_surfaced"),
            save_face_pivot_used=bool(data.get("_save_face_pivot_used", False)),
        )


def initial_candidate_state() -> dict:
    return CandidateState().to_dict()


def update_disengagement(state_dict: dict, signal: str) -> float:
    """Apply a disengagement signal to the orchestrator's 0-5 state model."""
    cs = state_dict.setdefault("candidate_state", {})
    current = float(cs.get("disengagement_level", 0.0))
    delta = DISENGAGEMENT_INCREMENTS.get(signal, 0.0)
    new_level = max(0.0, min(5.0, current + delta))
    cs["disengagement_level"] = new_level
    return new_level


def check_topic_fatigue(state_dict: dict, focus_key: str) -> bool:
    cs = state_dict.get("candidate_state", {})
    threshold = int(cs.get("topic_fatigue_threshold", 4))
    count = int((cs.get("topic_fatigue") or {}).get(focus_key, 0))
    return count >= threshold


def get_topic_fatigue_ratio(state_dict: dict, focus_key: str) -> float:
    fatigue = (state_dict.get("candidate_state", {}) or {}).get("topic_fatigue", {}) or {}
    total = sum(int(v) for v in fatigue.values())
    if total == 0:
        return 0.0
    return int(fatigue.get(focus_key, 0)) / total


def detect_communication_mode(turn1_text: str, turn2_text: str) -> str:
    """
    Run on the first two answers. Returns: normal | simplified | narrative_only.
    Looks for repeated words and near-empty shutdown responses.
    """
    combined = f"{turn1_text} {turn2_text}".lower()
    words = combined.split()
    repetition_count = sum(
        1 for i in range(len(words) - 1) if words[i] == words[i + 1]
    )
    shutdown_count = sum(
        1 for count in (len(turn1_text.split()), len(turn2_text.split()))
        if count < 5
    )
    if repetition_count >= 3:
        return "simplified"
    if shutdown_count >= 2:
        return "narrative_only"
    return "normal"
