from __future__ import annotations

import time
from typing import Any

from backend.models.action_deck import (
    RecoveryDeckRequest,
    SpokenQuestionCommit,
    VoiceCommitTurnRequest,
    VoiceEvent,
)
from backend.services.interview_telemetry import interview_telemetry
from backend.services.voice_policy import VoicePolicyKernel


class VoiceAgentGateway:
    """Thin IO boundary between Realtime voice clients and the interview brain."""

    def __init__(self, orchestrator, policy_kernel: VoicePolicyKernel | None = None):
        self.orchestrator = orchestrator
        self.policy = policy_kernel or VoicePolicyKernel()

    async def action_deck(self, session_id: str, *, turn_id: str = "") -> dict[str, Any]:
        state = await self.orchestrator.session_manager.get_state(session_id)
        deck = self.policy.compile_action_deck(state, turn_id=turn_id)
        decision = self.policy.decide(state, deck)
        state["last_voice_policy_decision"] = decision.model_dump()
        self._append_policy_event(state, decision.model_dump())
        await self.orchestrator.session_manager.save_state(session_id, state)
        await interview_telemetry.log(
            session_id,
            "voice.action_deck",
            source="backend.voice",
            deck_status=deck.status,
            decision_status=decision.status,
            reason_code=decision.reason_code,
        )
        return {"action_deck": deck.model_dump(), "policy_decision": decision.model_dump()}

    async def policy_decision(self, session_id: str, *, event_type: str = "", require_spoken_question: bool = False) -> dict[str, Any]:
        state = await self.orchestrator.session_manager.get_state(session_id)
        deck = self.policy.compile_action_deck(state)
        decision = self.policy.decide(
            state,
            deck,
            event_type=event_type,
            require_spoken_question=require_spoken_question,
        )
        state["last_voice_policy_decision"] = decision.model_dump()
        self._append_policy_event(state, decision.model_dump())
        await self.orchestrator.session_manager.save_state(session_id, state)
        await interview_telemetry.log(
            session_id,
            "voice.policy_decision",
            source="backend.voice",
            decision_status=decision.status,
            reason_code=decision.reason_code,
            event_type=event_type,
        )
        return {"action_deck": deck.model_dump(), "policy_decision": decision.model_dump()}

    async def spoken_question(self, commit: SpokenQuestionCommit) -> dict[str, Any]:
        state = await self.orchestrator.session_manager.get_state(commit.session_id)
        updated, rejection = self.policy.commit_spoken_question(state, commit)
        if rejection:
            state["last_voice_policy_decision"] = rejection.model_dump()
            self._append_policy_event(state, rejection.model_dump())
            await self.orchestrator.session_manager.save_state(commit.session_id, state)
            return {
                "ok": False,
                "spoken_question_commit": updated.model_dump(),
                "policy_decision": rejection.model_dump(),
            }
        await self.orchestrator.session_manager.save_state(commit.session_id, state)
        await interview_telemetry.log(
            commit.session_id,
            "voice.spoken_question_committed",
            source="backend.voice",
            selected_move_id=updated.selected_move_id,
            route_kind=updated.route_kind,
            semantic_drift_score=updated.semantic_drift_score,
        )
        return {"ok": True, "spoken_question_commit": updated.model_dump()}

    async def event(self, event: VoiceEvent) -> dict[str, Any]:
        state = await self.orchestrator.session_manager.get_state(event.session_id)
        interaction = event.model_dump()
        interaction["recorded_at_ms"] = int(time.time() * 1000)
        state.setdefault("interaction_events", []).append(interaction)
        state["interaction_events"] = state["interaction_events"][-200:]
        items = state.setdefault("transcript_items_by_provider", {})
        provider_items = items.setdefault(event.provider, {})
        if event.item_id:
            provider_items[event.item_id] = {
                "transcript": event.transcript,
                "is_final": event.is_final,
                "turn_id": event.turn_id,
                "updated_at_ms": interaction["recorded_at_ms"],
            }
        await self.orchestrator.session_manager.save_state(event.session_id, state)

        if event.transcript and not event.is_final:
            await self.orchestrator.on_partial_transcript(
                event.session_id,
                event.transcript,
                entities=[],
                turn_id=event.turn_id,
                is_final=False,
                snapshot_seq=event.snapshot_seq,
            )
        await interview_telemetry.log(
            event.session_id,
            "voice.event",
            source="backend.voice",
            event_type=event.event_type,
            provider=event.provider,
            turn_id=event.turn_id,
            item_id=event.item_id,
            is_final=event.is_final,
        )
        return {"ok": True}

    async def commit_turn(self, data: VoiceCommitTurnRequest) -> dict[str, Any]:
        state = await self.orchestrator.session_manager.get_state(data.session_id)
        deck = self.policy.compile_action_deck(state, turn_id=data.turn_id)
        gate = self.policy.decide(state, deck, require_spoken_question=True)
        if gate.status != "ALLOW_ASSESSMENT":
            state["last_voice_policy_decision"] = gate.model_dump()
            self._append_policy_event(state, gate.model_dump())
            await self.orchestrator.session_manager.save_state(data.session_id, state)
            return {
                "ok": False,
                "blocked": True,
                "policy_decision": gate.model_dump(),
                "action_deck": deck.model_dump(),
            }

        result = await self.orchestrator.handle_transcript(
            data.session_id,
            data.transcript,
            entities=data.entities,
            turn_id=data.turn_id,
        )
        fresh_state = await self.orchestrator.session_manager.get_state(data.session_id)
        next_deck = self.policy.compile_action_deck(fresh_state, turn_id=data.turn_id)
        next_decision = self.policy.decide(fresh_state, next_deck)
        fresh_state["last_voice_policy_decision"] = next_decision.model_dump()
        self._append_policy_event(fresh_state, next_decision.model_dump())
        await self.orchestrator.session_manager.save_state(data.session_id, fresh_state)
        return {
            "ok": True,
            "turn_result": result,
            "action_deck": next_deck.model_dump(),
            "policy_decision": next_decision.model_dump(),
        }

    async def recovery_deck(self, data: RecoveryDeckRequest) -> dict[str, Any]:
        state = await self.orchestrator.session_manager.get_state(data.session_id)
        deck = self.policy.recovery_deck(state, data.reason, turn_id=data.turn_id)
        decision = self.policy.decide(state, deck, event_type=data.reason)
        state["last_voice_policy_decision"] = decision.model_dump()
        self._append_policy_event(state, decision.model_dump())
        await self.orchestrator.session_manager.save_state(data.session_id, state)
        await interview_telemetry.log(
            data.session_id,
            "voice.recovery_deck",
            source="backend.voice",
            reason=data.reason,
            decision_status=decision.status,
        )
        return {"action_deck": deck.model_dump(), "policy_decision": decision.model_dump()}

    def _append_policy_event(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        event = dict(event)
        event["recorded_at_ms"] = int(time.time() * 1000)
        state.setdefault("voice_policy_events", []).append(event)
        state["voice_policy_events"] = state["voice_policy_events"][-200:]
