import asyncio
import json
import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")

from backend.models.action_deck import SpokenQuestionCommit, VoiceCommitTurnRequest
from backend.services.voice_agent_gateway import VoiceAgentGateway
from backend.services.voice_policy import VoicePolicyKernel
from backend.api.routes import VoiceRealtimeOfferRequest, _voice_realtime_session_config, router


def _state(**overrides):
    state = {
        "session_id": "voice-session",
        "interview_started": True,
        "interview_map_status": "ready",
        "question_count": 3,
        "resume": "FULL_SECRET_RESUME_SHOULD_NOT_LEAK",
        "parsed_resume": {"skills": ["SQL", "experimentation", "telemetry"]},
        "target_role": "Product Analyst",
        "weaknesses": [{"hidden": "RAW_WEAKNESS_LEDGER_SHOULD_NOT_LEAK"}],
        "interview_trajectory_map": {"hidden": "FULL_MAP_SHOULD_NOT_LEAK"},
        "last_question": "What exact definition of churn did you use for buyer cohorts?",
        "current_answer_response": "What exact definition of churn did you use for buyer cohorts?",
        "active_question_packet": {
            "question_text": "What exact definition of churn did you use for buyer cohorts?",
            "route_kind": "trajectory_map_surface",
            "agenda_phase": "primary_depth",
            "focus_key": "cohort_retention",
            "focus_label": "Cohort Retention",
            "question_posture": "clarify",
            "signal_goal": "Validate metric definition precision.",
            "expected_space": ["activation event", "churn window"],
            "voice_complexity": "low",
        },
        "history": [],
    }
    state.update(overrides)
    return state


def _decision_status(state, event_type="", require_spoken_question=False):
    kernel = VoicePolicyKernel()
    deck = kernel.compile_action_deck(state)
    return kernel.decide(
        state,
        deck,
        event_type=event_type,
        require_spoken_question=require_spoken_question,
    )


def test_action_deck_redacts_hidden_interview_state() -> None:
    kernel = VoicePolicyKernel()
    deck = kernel.compile_action_deck(_state())

    payload = json.dumps(deck.model_dump())

    assert deck.status == "ready"
    assert "FULL_SECRET_RESUME_SHOULD_NOT_LEAK" not in payload
    assert "RAW_WEAKNESS_LEDGER_SHOULD_NOT_LEAK" not in payload
    assert "FULL_MAP_SHOULD_NOT_LEAK" not in payload
    assert deck.selected_move is not None
    assert deck.selected_move.counts_as_assessment_turn is True


def test_same_surface_warning_requires_pivot() -> None:
    state = _state(
        last_policy_check={
            "warnings": [
                {
                    "code": "same_surface_streak",
                    "severity": "high",
                    "suggested_action": "stop_same_surface",
                }
            ]
        }
    )

    decision = _decision_status(state)

    assert decision.status == "REQUIRE_PIVOT"
    assert decision.reason_code == "same_surface_streak"
    assert decision.blocked_warning_codes == ["same_surface_streak"]


def test_map_focus_missing_fails_closed() -> None:
    state = _state(
        active_question_packet={
            "question_text": "How would you test whether that lift is real?",
            "route_kind": "application_transfer",
            "focus_key": "",
        },
        last_policy_check={
            "warnings": [
                {
                    "code": "map_focus_missing",
                    "severity": "high",
                    "suggested_action": "fail_closed_or_repair_packet",
                }
            ]
        },
    )

    decision = _decision_status(state)

    assert decision.status == "FAIL_CLOSED"
    assert decision.reason_code == "map_focus_missing"


def test_interaction_event_does_not_allow_assessment_commit() -> None:
    decision = _decision_status(_state(), event_type="slow_down_requested")

    assert decision.status == "REQUIRE_REPHRASE"
    assert decision.requires_spoken_commit is False


def test_spoken_question_commit_rewrites_canonical_question() -> None:
    kernel = VoicePolicyKernel()
    state = _state()
    deck = kernel.compile_action_deck(state)
    move = deck.selected_move
    assert move is not None

    commit, rejection = kernel.commit_spoken_question(
        state,
        SpokenQuestionCommit(
            session_id="voice-session",
            turn_id="question-turn-1",
            selected_move_id=move.move_id,
            backend_question=move.question,
            spoken_text="What exact churn definition did you use for buyer cohorts?",
        ),
    )

    assert rejection is None
    assert commit.backend_intent_preserved is True
    assert state["last_question"] == "What exact churn definition did you use for buyer cohorts?"
    assert state["current_answer_response"] == "What exact churn definition did you use for buyer cohorts?"
    assert state["active_question_packet"]["question_text"] == "What exact churn definition did you use for buyer cohorts?"
    assert state["spoken_question_commits"]


def test_semantic_drift_rejected_before_evaluation() -> None:
    kernel = VoicePolicyKernel()
    state = _state()
    deck = kernel.compile_action_deck(state)
    move = deck.selected_move
    assert move is not None

    commit, rejection = kernel.commit_spoken_question(
        state,
        SpokenQuestionCommit(
            session_id="voice-session",
            selected_move_id=move.move_id,
            backend_question=move.question,
            spoken_text="Tell me about your favorite project.",
        ),
    )

    assert commit.backend_intent_preserved is False
    assert rejection is not None
    assert rejection.status == "REQUIRE_RECOVERY"
    assert rejection.recovery_reason == "semantic_drift_rejected"
    assert not state.get("spoken_question_commits")


def test_duplicate_closing_is_blocked() -> None:
    state = _state(
        active_question_packet={
            "question_text": "Before we finish, is there anything we did not cover?",
            "route_kind": "synthesis_close",
            "focus_key": "cohort_retention",
        },
        history=[{"route_kind": "synthesis_close"}],
    )

    decision = _decision_status(state)

    assert decision.status == "REQUIRE_RECOVERY"
    assert decision.recovery_reason == "duplicate_closing"


class _FakeSessionManager:
    def __init__(self, state):
        self.state = state

    async def get_state(self, session_id):
        if session_id != self.state["session_id"]:
            raise KeyError(session_id)
        return self.state

    async def save_state(self, session_id, state):
        self.state = state


class _FakeOrchestrator:
    def __init__(self, state):
        self.session_manager = _FakeSessionManager(state)
        self.handle_called = False

    async def handle_transcript(self, *args, **kwargs):
        self.handle_called = True
        return {"response": "next question", "route_kind": "trajectory_map_surface"}

    async def on_partial_transcript(self, *args, **kwargs):
        return None


def test_voice_commit_turn_requires_spoken_question_commit() -> None:
    async def run():
        state = _state()
        orchestrator = _FakeOrchestrator(state)
        gateway = VoiceAgentGateway(orchestrator)

        result = await gateway.commit_turn(
            VoiceCommitTurnRequest(
                session_id="voice-session",
                transcript="I used a 90-day churn window.",
                turn_id="answer-turn-1",
            )
        )

        assert result["blocked"] is True
        assert result["policy_decision"]["status"] == "REQUIRE_RECOVERY"
        assert result["policy_decision"]["recovery_reason"] == "spoken_commit_missing"
        assert orchestrator.handle_called is False

    asyncio.run(run())


def test_voice_routes_are_registered() -> None:
    paths = {route.path for route in router.routes}

    assert "/voice/action_deck/{session_id}" in paths
    assert "/voice/policy_decision" in paths
    assert "/voice/spoken_question" in paths
    assert "/voice/event" in paths
    assert "/voice/commit_turn" in paths
    assert "/voice/recovery_deck" in paths
    assert "/voice/status" in paths
    assert "/voice/openai/realtime_offer" in paths
    assert "/voice/openai/transcribe_audio/{session_id}" in paths


def test_realtime_session_is_manual_response_only_and_interview_bound() -> None:
    config = _voice_realtime_session_config(
        VoiceRealtimeOfferRequest(
            session_id="voice-session",
            sdp="v=0",
            model="gpt-realtime-mini",
            vad_mode="semantic_vad",
            vad_eagerness="low",
        )
    )

    turn_detection = config["audio"]["input"]["turn_detection"]

    assert config["model"] == "gpt-realtime-mini"
    assert turn_detection["type"] == "semantic_vad"
    assert turn_detection["eagerness"] == "low"
    assert turn_detection["create_response"] is False
    assert turn_detection["interrupt_response"] is False
    assert "always inside a live interview" in config["instructions"]
    assert "never a general assistant" in config["instructions"]
