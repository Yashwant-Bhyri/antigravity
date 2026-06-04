from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MoveType = Literal["assessment", "interaction", "recovery", "closing", "operational"]
DeckStatus = Literal["ready", "empty", "degraded", "no_launch", "failed_closed"]
PolicyDecisionStatus = Literal[
    "ALLOW_ASSESSMENT",
    "ALLOW_INTERACTION",
    "REQUIRE_REPHRASE",
    "REQUIRE_CONTINUATION",
    "REQUIRE_PIVOT",
    "REQUIRE_RECOVERY",
    "REQUIRE_PAUSE",
    "FAIL_CLOSED",
]


class DeliveryPolicy(BaseModel):
    one_question_only: bool = True
    max_sentences: int = 2
    max_semantic_drift: Literal["none", "low", "medium"] = "low"
    allow_light_grammar_repair: bool = True
    allow_slowdown: bool = True
    allow_repeat: bool = True
    allow_barge_in: bool = True
    vad_mode: Literal["semantic_vad", "server_vad"] = "semantic_vad"
    vad_eagerness: Literal["low", "medium", "high", "auto"] = "low"
    voice_model: str = "gpt-realtime-mini"


class ActionMove(BaseModel):
    move_id: str
    move_type: MoveType = "assessment"
    question: str = ""
    counts_as_assessment_turn: bool = True
    route_kind: str = ""
    agenda_phase: str = ""
    focus_key: str = ""
    focus_label: str = ""
    coverage_dimension_id: str = ""
    coverage_dimension_label: str = ""
    question_posture: str = ""
    signal_goal: str = ""
    expected_space: list[str] = Field(default_factory=list)
    voice_complexity: str = ""
    allowed_rephrase_scope: Literal["none", "grammar", "light", "simplify"] = "light"
    must_preserve: list[str] = Field(default_factory=list)
    invalid_if: list[str] = Field(default_factory=list)
    policy_risk: Literal["low", "medium", "high"] = "low"
    source: str = "active_question_packet"


class ActionDeck(BaseModel):
    deck_id: str
    session_id: str
    turn_id: str = ""
    status: DeckStatus = "ready"
    selected_move: ActionMove | None = None
    reserve_moves: list[ActionMove] = Field(default_factory=list)
    recovery_moves: list[ActionMove] = Field(default_factory=list)
    delivery_policy: DeliveryPolicy = Field(default_factory=DeliveryPolicy)
    candidate_state_summary: dict[str, Any] = Field(default_factory=dict)
    policy_constraints: list[dict[str, Any]] = Field(default_factory=list)
    do_not_do: list[str] = Field(default_factory=list)
    small_resume_snippet_cards: list[dict[str, str]] = Field(default_factory=list)
    expires_after_turn: int = 0
    degraded_reason: str = ""


class VoicePolicyDecision(BaseModel):
    status: PolicyDecisionStatus
    reason_code: str
    selected_move_id: str = ""
    recovery_reason: str = ""
    requires_spoken_commit: bool = False
    one_question_only: bool = True
    max_sentences: int = 2
    delivery_tone: str = "curious_direct"
    instructions: str = ""
    blocked_warning_codes: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class SpokenQuestionCommit(BaseModel):
    session_id: str
    turn_id: str = ""
    selected_move_id: str
    backend_question: str
    spoken_text: str
    route_kind: str = ""
    backend_intent_preserved: bool = True
    semantic_drift_score: float = 0.0
    spoken_at_ms: int = 0


class VoiceEvent(BaseModel):
    session_id: str
    event_type: str
    provider: str = "openai"
    turn_id: str = ""
    item_id: str = ""
    transcript: str = ""
    is_final: bool = False
    snapshot_seq: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceCommitTurnRequest(BaseModel):
    session_id: str
    transcript: str
    turn_id: str = ""
    item_id: str = ""
    entities: list[str] = Field(default_factory=list)
    spoken_question_turn_id: str = ""


class RecoveryDeckRequest(BaseModel):
    session_id: str
    reason: str
    turn_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
