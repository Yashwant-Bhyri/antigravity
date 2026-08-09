"""Deterministic backend contract tests for the isolated InterviewTraceV1 module."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path

try:
    from backend.services.interview_trace_v1 import (
        InterviewTraceV1,
        TraceEventType,
        TraceImmutableDecisionError,
        TraceIntegrityError,
        TraceInvariantError,
        TraceReferenceError,
        TraceView,
    )
except ModuleNotFoundError:  # direct execution from the backend directory
    from services.interview_trace_v1 import (
        InterviewTraceV1,
        TraceEventType,
        TraceImmutableDecisionError,
        TraceIntegrityError,
        TraceInvariantError,
        TraceReferenceError,
        TraceView,
    )


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000

    def __call__(self) -> int:
        self.value += 1
        return self.value


def _keys(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            result.add(str(key))
            result.update(_keys(child))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            result.update(_keys(child))
    return result


class InterviewTraceV1ContractTests(unittest.TestCase):
    def trace(self) -> InterviewTraceV1:
        return InterviewTraceV1("session-contract", clock=_Clock())

    def opening(self, trace: InterviewTraceV1, turn_id: str = "turn-1") -> dict[str, object]:
        session = trace.events[0]
        validation = trace.record_state_transition_validated(
            turn_id=turn_id,
            answer_version=1,
            decision="accepted",
            visible_route_commit_allowed=True,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key=f"validation:{turn_id}",
        )
        materialized = trace.record_question_materialized(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question-{turn_id}",
            visible_text="Tell me about the system.",
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key=f"materialized:{turn_id}",
        )
        prepared = trace.record_question_prepared(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question-{turn_id}",
            materialized_event_id=materialized.event_id,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key=f"prepared:{turn_id}",
        )
        started = trace.record_question_delivery_started(
            turn_id=turn_id,
            answer_version=1,
            question_prepared_event_id=prepared.event_id,
            delivery_attempt_id=f"attempt-{turn_id}-1",
            provider="cartesia",
            idempotency_key=f"delivery-start:{turn_id}",
        )
        acknowledged = trace.record_playback_acknowledged(
            turn_id=turn_id,
            answer_version=1,
            delivery_attempt_id=f"attempt-{turn_id}-1",
            delivery_started_event_id=started.event_id,
            idempotency_key=f"playback-ack:{turn_id}",
        )
        spoken = trace.record_spoken_question_committed(
            turn_id=turn_id,
            answer_version=1,
            question_id=f"question-{turn_id}",
            visible_text="Tell me about the system.",
            question_materialized_event_id=materialized.event_id,
            playback_ack_event_id=acknowledged.event_id,
            delivery_attempt_id=f"attempt-{turn_id}-1",
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key=f"spoken:{turn_id}",
        )
        self.assertTrue(validation.accepted)
        self.assertTrue(spoken.accepted)
        return {"session": session, "validation": validation.event, "materialized": materialized.event,
                "prepared": prepared.event, "started": started.event, "ack": acknowledged.event,
                "spoken": spoken.event}

    def answer_inventory(self, trace: InterviewTraceV1, opening: dict[str, object]) -> dict[str, object]:
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="I owned the event boundary and measured the failure mode.",
            idempotency_key="answer:turn-1:1",
        )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"owned_surface": "event-boundary", "confidence": 0.91},
            idempotency_key="semantic-final:turn-1:1",
        )
        inventory = trace.record_opportunity_inventory_compiled(
            turn_id="turn-1", answer_version=1, semantic_event_id=semantic.event_id,
            admitted_candidates=[
                {"opportunity_id": "opp-next", "kind": "probe-boundary", "surface_id": "surface-1",
                 "evidence_event_ids": [semantic.event_id]},
                {"opportunity_id": "opp-retry", "kind": "probe-retry", "surface_id": "surface-2",
                 "evidence_event_ids": [semantic.event_id]},
            ],
            excluded_candidates=[
                {"opportunity_id": "opp-excluded", "reason": "unsupported", "evidence_event_ids": [semantic.event_id]}
            ],
            idempotency_key="inventory:turn-1:1",
        )
        evidence = trace.record_evidence_state_updated(
            turn_id="turn-1", answer_version=1, semantic_event_id=semantic.event_id,
            opportunity_inventory_event_id=inventory.event_id,
            evidence_state={"owned_surface_confirmed": True, "coverage": "partial"},
            source_event_ids=[semantic.event_id, inventory.event_id], idempotency_key="evidence:turn-1:1",
        )
        return {"answer": answer.event, "semantic": semantic.event, "inventory": inventory.event,
                "evidence": evidence.event}

    def next_question(self, trace: InterviewTraceV1, source: dict[str, object], *, turn_id: str = "turn-2",
                      opportunity_id: str = "opp-next", prior: object | None = None) -> dict[str, object]:
        prior_event = prior if prior is not None else trace.last_spoken_question_event_id
        grant = trace.record_action_grant_selected(
            turn_id=turn_id, answer_version=1, opportunity_inventory_event_id=source["inventory"].event_id,
            opportunity_id=opportunity_id, source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior_event.event_id if hasattr(prior_event, "event_id") else str(prior_event),
            action="probe-boundary", idempotency_key=f"grant:{turn_id}",
        )
        prior_id = prior_event.event_id if hasattr(prior_event, "event_id") else str(prior_event)
        validation = trace.record_state_transition_validated(
            turn_id=turn_id, answer_version=1, decision="accepted", visible_route_commit_allowed=True,
            source_opportunity_id=opportunity_id, source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior_id, action_grant_event_id=grant.event_id,
            idempotency_key=f"validation:{turn_id}",
        )
        materialized = trace.record_question_materialized(
            turn_id=turn_id, answer_version=1, question_id=f"question-{turn_id}",
            visible_text=f"What trade-off did you make in {turn_id}?", source_opportunity_id=opportunity_id,
            source_evidence_event_ids=[source["semantic"].event_id], prior_spoken_question_event_id=prior_id,
            action_grant_event_id=grant.event_id, route_kind="depth", idempotency_key=f"materialized:{turn_id}",
        )
        prepared = trace.record_question_prepared(
            turn_id=turn_id, answer_version=1, question_id=f"question-{turn_id}",
            materialized_event_id=materialized.event_id, source_opportunity_id=opportunity_id,
            source_evidence_event_ids=[source["semantic"].event_id], prior_spoken_question_event_id=prior_id,
            idempotency_key=f"prepared:{turn_id}",
        )
        started = trace.record_question_delivery_started(
            turn_id=turn_id, answer_version=1, question_prepared_event_id=prepared.event_id,
            delivery_attempt_id=f"attempt-{turn_id}-1", provider="cartesia",
            idempotency_key=f"delivery-start:{turn_id}",
        )
        acknowledged = trace.record_playback_acknowledged(
            turn_id=turn_id, answer_version=1, delivery_attempt_id=f"attempt-{turn_id}-1",
            delivery_started_event_id=started.event_id, idempotency_key=f"playback-ack:{turn_id}",
        )
        spoken = trace.record_spoken_question_committed(
            turn_id=turn_id, answer_version=1, question_id=f"question-{turn_id}",
            visible_text=f"What trade-off did you make in {turn_id}?",
            question_materialized_event_id=materialized.event_id, playback_ack_event_id=acknowledged.event_id,
            delivery_attempt_id=f"attempt-{turn_id}-1", prior_spoken_question_event_id=prior_id,
            source_opportunity_id=opportunity_id, source_evidence_event_ids=[source["semantic"].event_id],
            idempotency_key=f"spoken:{turn_id}",
        )
        self.assertTrue(validation.accepted)
        self.assertTrue(spoken.accepted)
        return {"grant": grant.event, "validation": validation.event, "materialized": materialized.event,
                "prepared": prepared.event, "started": started.event, "ack": acknowledged.event,
                "spoken": spoken.event}

    def retriable_question(self, trace: InterviewTraceV1, source: dict[str, object], prior: dict[str, object]) -> dict[str, object]:
        turn_id = "turn-3"
        grant = trace.record_action_grant_selected(
            turn_id=turn_id, answer_version=1, opportunity_inventory_event_id=source["inventory"].event_id,
            opportunity_id="opp-retry", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior["spoken"].event_id, action="probe-retry",
            idempotency_key="grant:turn-3",
        )
        validation = trace.record_state_transition_validated(
            turn_id=turn_id, answer_version=1, decision="accepted", visible_route_commit_allowed=True,
            source_opportunity_id="opp-retry", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior["spoken"].event_id, action_grant_event_id=grant.event_id,
            idempotency_key="validation:turn-3",
        )
        materialized = trace.record_question_materialized(
            turn_id=turn_id, answer_version=1, question_id="question-turn-3", visible_text="How did you measure it?",
            source_opportunity_id="opp-retry", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior["spoken"].event_id, action_grant_event_id=grant.event_id,
            idempotency_key="materialized:turn-3",
        )
        prepared = trace.record_question_prepared(
            turn_id=turn_id, answer_version=1, question_id="question-turn-3", materialized_event_id=materialized.event_id,
            source_opportunity_id="opp-retry", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior["spoken"].event_id, idempotency_key="prepared:turn-3",
        )
        first = trace.record_question_delivery_started(
            turn_id=turn_id, answer_version=1, question_prepared_event_id=prepared.event_id,
            delivery_attempt_id="attempt-turn-3-1", provider="cartesia", idempotency_key="delivery-start:turn-3:1",
        )
        failed = trace.record_delivery_failed(
            turn_id=turn_id, answer_version=1, delivery_attempt_id="attempt-turn-3-1",
            delivery_started_event_id=first.event_id, reason="audio_error", idempotency_key="delivery-failed:turn-3:1",
        )
        self.assertFalse(any(event.turn_id == turn_id and event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for event in trace.events))
        second = trace.record_question_delivery_started(
            turn_id=turn_id, answer_version=1, question_prepared_event_id=prepared.event_id,
            delivery_attempt_id="attempt-turn-3-2", provider="cartesia", idempotency_key="delivery-start:turn-3:2",
        )
        acknowledged = trace.record_playback_acknowledged(
            turn_id=turn_id, answer_version=1, delivery_attempt_id="attempt-turn-3-2",
            delivery_started_event_id=second.event_id, idempotency_key="playback-ack:turn-3:2",
        )
        spoken = trace.record_spoken_question_committed(
            turn_id=turn_id, answer_version=1, question_id="question-turn-3", visible_text="How did you measure it?",
            question_materialized_event_id=materialized.event_id, playback_ack_event_id=acknowledged.event_id,
            delivery_attempt_id="attempt-turn-3-2", prior_spoken_question_event_id=prior["spoken"].event_id,
            source_opportunity_id="opp-retry", source_evidence_event_ids=[source["semantic"].event_id],
            idempotency_key="spoken:turn-3",
        )
        self.assertTrue(validation.accepted)
        self.assertTrue(spoken.accepted)
        return {"grant": grant.event, "validation": validation.event, "failed": failed.event, "spoken": spoken.event}

    def test_happy_path_causal_sequence_and_final_evaluation(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        next_question = self.next_question(trace, source)
        answer = trace.record_answer_received(
            turn_id="turn-2", answer_version=1, spoken_question_event_id=next_question["spoken"].event_id,
            answer_text="I chose bounded retries and measured user-visible failure.", idempotency_key="answer:turn-2:1",
        )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-2", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"tradeoff": "bounded-retry"}, idempotency_key="semantic-final:turn-2:1",
        )
        claim = trace.record_report_claim_emitted(
            claim_id="claim-1", claim_text="Candidate articulated a bounded retry trade-off.",
            source_evidence_event_ids=[source["evidence"].event_id, semantic.event_id], idempotency_key="claim:1",
        )
        final = trace.record_final_evaluation_completed(
            evaluation_id="evaluation-1", report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[source["evidence"].event_id, semantic.event_id],
            evaluation_summary={"coverage": "complete"}, idempotency_key="evaluation:1",
        )
        self.assertTrue(final.accepted)
        spoken = next(event for event in trace.events if event.event_id == next_question["spoken"].event_id)
        self.assertEqual(spoken.causal_parent_ids, (next_question["materialized"].event_id, next_question["ack"].event_id))
        self.assertTrue(trace.verify_integrity())
        self.assertIn(TraceEventType.FINAL_EVALUATION_COMPLETED.value, [event.event_type for event in trace.events])

    def test_failed_tts_has_no_spoken_truth_but_retry_can_succeed(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        prior = self.next_question(trace, source)
        retried = self.retriable_question(trace, source, prior)
        self.assertEqual(retried["failed"].event_type, TraceEventType.DELIVERY_FAILED.value)
        self.assertEqual(retried["spoken"].event_type, TraceEventType.SPOKEN_QUESTION_COMMITTED.value)
        self.assertEqual([item["turn_id"] for item in trace.canonical_spoken_history()], ["turn-1", "turn-2", "turn-3"])
        self.assertTrue(trace.verify_integrity())

    def test_duplicate_process_turn_retry_is_idempotent(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        first = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="same answer", idempotency_key="process-turn:turn-1:1",
        )
        second = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="same answer", idempotency_key="process-turn:turn-1:1",
        )
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(sum(event.event_type == TraceEventType.ANSWER_RECEIVED.value for event in trace.events), 1)

    def test_first_and_repeated_stale_attempts_are_rejected(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        trace.advance_runtime_epoch(1)
        first = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="stale answer", runtime_epoch=0, idempotency_key="stale-process-turn:1",
        )
        second = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="stale answer", runtime_epoch=0, idempotency_key="stale-process-turn:1",
        )
        self.assertFalse(first.accepted)
        self.assertFalse(first.idempotent)
        self.assertEqual(first.reason, "stale_runtime_epoch")
        self.assertFalse(second.accepted)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.event_id, second.event_id)
        rejection_events = [
            event for event in trace.events
            if event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value
            and event.payload["views"][TraceView.EVALUATOR.value].get("validation_status") == "rejected"
        ]
        self.assertEqual(len(rejection_events), 1)
        self.assertFalse(any(event.event_type == TraceEventType.ANSWER_RECEIVED.value for event in trace.events))
        reloaded = InterviewTraceV1.from_records(trace.export_records())
        self.assertEqual(trace.canonical_spoken_history(), reloaded.canonical_spoken_history())
        self.assertTrue(reloaded.verify_integrity())

    def test_rejected_validation_receipt_and_no_visible_route_commit(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        prior = trace.last_spoken_question_event_id
        grant = trace.record_action_grant_selected(
            turn_id="turn-2", answer_version=1, opportunity_inventory_event_id=source["inventory"].event_id,
            opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior, action="probe-boundary", idempotency_key="grant:rejected",
        )
        rejected = trace.record_state_transition_validated(
            turn_id="turn-2", answer_version=1, decision="rejected", visible_route_commit_allowed=True,
            source_opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior, action_grant_event_id=grant.event_id, reason="validation rejected",
            idempotency_key="validation:rejected",
        )
        repeated = trace.record_state_transition_validated(
            turn_id="turn-2", answer_version=1, decision="rejected", visible_route_commit_allowed=True,
            source_opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=prior, action_grant_event_id=grant.event_id, reason="validation rejected",
            idempotency_key="validation:rejected",
        )
        self.assertFalse(rejected.accepted)
        self.assertFalse(rejected.idempotent)
        self.assertFalse(repeated.accepted)
        self.assertTrue(repeated.idempotent)
        with self.assertRaises(TraceInvariantError):
            trace.record_question_materialized(
                turn_id="turn-2", answer_version=1, question_id="question-rejected",
                visible_text="Must not be visible.", source_opportunity_id="opp-next",
                source_evidence_event_ids=[source["semantic"].event_id], prior_spoken_question_event_id=prior,
                action_grant_event_id=grant.event_id, idempotency_key="materialized:rejected",
            )
        self.assertFalse(any(event.turn_id == "turn-2" and event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for event in trace.events))

    def test_semantic_shadow_disagreement_cannot_overwrite_final(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="I owned the boundary.", idempotency_key="answer:shadow",
        )
        final = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"meaning": "owned-boundary"}, idempotency_key="semantic-final:shadow",
        )
        shadow = trace.record_semantic_interpretation_shadow(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id, finalized_event_id=final.event_id,
            interpretation={"meaning": "framework-only"}, disagreement={"kind": "disagreement"},
            idempotency_key="semantic-shadow:shadow",
        )
        final_view = next(event for event in trace.events if event.event_id == final.event_id).payload["views"][TraceView.EVALUATOR.value]
        self.assertTrue(shadow.accepted)
        self.assertEqual(final_view["interpretation"]["meaning"], "owned-boundary")
        with self.assertRaises(TraceImmutableDecisionError):
            trace.record_semantic_interpretation_finalized(
                turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
                interpretation={"meaning": "overwrite"}, idempotency_key="semantic-final:overwrite",
            )

    def test_actor_projection_has_no_leakage_across_all_event_types(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        prior = self.next_question(trace, source)
        self.retriable_question(trace, source, prior)
        # Add a shadow and report/final events so every internal event family
        # is present in the same projection audit.
        answer = next(event for event in trace.events if event.event_type == TraceEventType.ANSWER_RECEIVED.value)
        semantic = next(event for event in trace.events if event.event_type == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value)
        trace.record_semantic_interpretation_shadow(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id, finalized_event_id=semantic.event_id,
            interpretation={"meaning": "shadow"}, disagreement={"kind": "shadow-only"}, idempotency_key="shadow:projection",
        )
        claim = trace.record_report_claim_emitted(
            claim_id="claim-projection", claim_text="hidden report judgment", source_evidence_event_ids=[source["evidence"].event_id],
            idempotency_key="claim:projection",
        )
        trace.record_final_evaluation_completed(
            evaluation_id="evaluation-projection", report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[source["evidence"].event_id], evaluation_summary={"hidden": "judgment"},
            idempotency_key="evaluation:projection",
        )
        trace.advance_runtime_epoch(1)

        forbidden = {
            "inventory_status", "admitted_count", "excluded_count", "admitted_candidates", "excluded_candidates",
            "action", "opportunity_id", "opportunity_inventory_event_id", "source_opportunity_id",
            "source_evidence_event_ids", "validation_status", "visible_route_commit_allowed", "reason",
            "interpretation", "disagreement", "semantic_status", "evidence_state", "evidence_state_hash",
            "claim_text", "evaluation_summary", "report_claim_event_ids", "hidden", "route_kind",
        }
        internal_events = {
            TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
            TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value,
            TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value,
            TraceEventType.ACTION_GRANT_SELECTED.value,
            TraceEventType.STATE_TRANSITION_VALIDATED.value,
            TraceEventType.EVIDENCE_STATE_UPDATED.value,
            TraceEventType.REPORT_CLAIM_EMITTED.value,
            TraceEventType.FINAL_EVALUATION_COMPLETED.value,
        }
        for event in trace.events:
            actor = event.payload.get("views", {}).get(TraceView.ACTOR.value, {})
            self.assertFalse(forbidden.intersection(_keys(actor)), event.event_type)
            if event.event_type in internal_events:
                self.assertEqual(dict(actor), {}, event.event_type)
        projected = trace.project(TraceView.ACTOR)
        self.assertTrue(all(item["event_type"] not in internal_events for item in projected))
        self.assertTrue(all(not forbidden.intersection(_keys(item["payload"])) for item in projected))
        self.assertTrue(any(item["event_type"] == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for item in projected))
        self.assertTrue(any(item["event_type"] == TraceEventType.ANSWER_RECEIVED.value for item in projected))

    def test_candidate_interviewer_evaluator_and_operator_projections_are_scoped(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        prior = self.next_question(trace, source)
        self.retriable_question(trace, source, prior)
        answer = next(event for event in trace.events if event.event_type == TraceEventType.ANSWER_RECEIVED.value)
        semantic = next(event for event in trace.events if event.event_type == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value)
        trace.record_semantic_interpretation_shadow(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id, finalized_event_id=semantic.event_id,
            interpretation={"meaning": "shadow"}, disagreement={"kind": "shadow-only"}, idempotency_key="shadow:views",
        )
        claim = trace.record_report_claim_emitted(
            claim_id="claim-views", claim_text="internal claim", source_evidence_event_ids=[source["evidence"].event_id],
            idempotency_key="claim:views",
        )
        trace.record_final_evaluation_completed(
            evaluation_id="evaluation-views", report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[source["evidence"].event_id], evaluation_summary={"hidden": "judgment"},
            idempotency_key="evaluation:views",
        )
        trace.advance_runtime_epoch(1)
        expected_event_types = {event_type.value for event_type in TraceEventType}
        self.assertEqual({event.event_type for event in trace.events}, expected_event_types)
        evaluator_only = {
            "interpretation", "disagreement", "admitted_candidates", "excluded_candidates", "evidence_state",
            "answer_text", "claim_text", "evaluation_summary", "source_evidence_event_ids", "source_opportunity_id",
            "action_grant_event_id", "opportunity_inventory_event_id", "validation_status", "route_kind",
        }
        candidate_hidden_events = {
            TraceEventType.RUNTIME_EPOCH_ADVANCED.value,
            TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
            TraceEventType.SEMANTIC_INTERPRETATION_SHADOW.value,
            TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value,
            TraceEventType.ACTION_GRANT_SELECTED.value,
            TraceEventType.STATE_TRANSITION_VALIDATED.value,
            TraceEventType.EVIDENCE_STATE_UPDATED.value,
            TraceEventType.REPORT_CLAIM_EMITTED.value,
            TraceEventType.FINAL_EVALUATION_COMPLETED.value,
        }
        for view in TraceView:
            projected = trace.project(view)
            for item in projected:
                self.assertNotIn("views", _keys(item["payload"]))
                self.assertNotIn("evaluator", _keys(item["payload"]))
            if view in {TraceView.CANDIDATE, TraceView.ACTOR}:
                self.assertTrue(all(item["event_type"] not in candidate_hidden_events for item in projected))
                self.assertTrue(all(not evaluator_only.intersection(_keys(item["payload"])) for item in projected))
            elif view == TraceView.INTERVIEWER:
                interviewer_hidden = evaluator_only - {"route_kind", "validation_status"}
                self.assertTrue(all(not interviewer_hidden.intersection(_keys(item["payload"])) for item in projected))
            elif view == TraceView.OPERATOR:
                self.assertTrue(all(not {"interpretation", "disagreement", "answer_text", "evaluation_summary"}.intersection(_keys(item["payload"])) for item in projected))
            else:
                self.assertTrue(any(item["event_type"] == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value for item in projected))

    def test_selected_action_and_spoken_question_preserve_exact_provenance(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        next_question = self.next_question(trace, source)
        grant_view = next(event for event in trace.events if event.event_id == next_question["grant"].event_id).payload["views"][TraceView.EVALUATOR.value]
        materialized_view = next(event for event in trace.events if event.event_id == next_question["materialized"].event_id).payload["views"][TraceView.EVALUATOR.value]
        spoken_view = next(event for event in trace.events if event.event_id == next_question["spoken"].event_id).payload["views"][TraceView.EVALUATOR.value]
        self.assertEqual(grant_view["opportunity_id"], "opp-next")
        self.assertEqual(grant_view["source_evidence_event_ids"], (source["semantic"].event_id,))
        self.assertEqual(grant_view["prior_spoken_question_event_id"], opening["spoken"].event_id)
        self.assertEqual(materialized_view["source_opportunity_id"], grant_view["opportunity_id"])
        self.assertEqual(materialized_view["source_evidence_event_ids"], grant_view["source_evidence_event_ids"])
        self.assertEqual(materialized_view["prior_spoken_question_event_id"], grant_view["prior_spoken_question_event_id"])
        self.assertEqual(spoken_view["source_opportunity_id"], materialized_view["source_opportunity_id"])
        self.assertEqual(spoken_view["source_evidence_event_ids"], materialized_view["source_evidence_event_ids"])
        self.assertEqual(spoken_view["prior_spoken_question_event_id"], materialized_view["prior_spoken_question_event_id"])
        self.assertIn(source["inventory"].event_id, next_question["grant"].causal_parent_ids)
        self.assertIn(opening["spoken"].event_id, next_question["grant"].causal_parent_ids)

    def test_delivery_failure_cannot_advance_evidence_or_coverage_truth(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        prior = self.next_question(trace, source)
        retried = self.retriable_question(trace, source, prior)
        self.assertFalse(any(event.turn_id == "turn-3" and event.event_type in {
            TraceEventType.ANSWER_RECEIVED.value,
            TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
            TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value,
            TraceEventType.EVIDENCE_STATE_UPDATED.value,
        } for event in trace.events))
        with self.assertRaises(TraceReferenceError):
            trace.record_evidence_state_updated(
                turn_id="turn-3", answer_version=1, semantic_event_id=source["semantic"].event_id,
                opportunity_inventory_event_id=source["inventory"].event_id,
                evidence_state={"coverage": "complete"},
                source_event_ids=[source["semantic"].event_id, source["inventory"].event_id],
                idempotency_key="evidence:turn-3:illegal",
            )
        self.assertEqual(retried["failed"].event_type, TraceEventType.DELIVERY_FAILED.value)
        self.assertTrue(any(event.turn_id == "turn-3" and event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for event in trace.events))

    def test_redaction_and_nested_payload_immutability(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="redaction fixture", idempotency_key="answer:redaction",
        )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"api_key": "sk-secret-value", "system_prompt": "do not leak", "meaning": "safe"},
            idempotency_key="semantic:redaction",
        )
        evaluator = next(event for event in trace.events if event.event_id == semantic.event_id).payload["views"][TraceView.EVALUATOR.value]
        self.assertEqual(evaluator["interpretation"]["api_key"], "[REDACTED]")
        self.assertEqual(evaluator["interpretation"]["system_prompt"], "[REDACTED]")
        before = trace.canonical_spoken_history()
        event = trace.events[0]
        self.assertIsInstance(event.causal_parent_ids, tuple)
        self.assertIsInstance(event.payload, Mapping)
        with self.assertRaises(TypeError):
            event.payload["views"][TraceView.CANDIDATE.value]["session_started"] = False
        with self.assertRaises(TypeError):
            event.payload["views"][TraceView.CANDIDATE.value] = {}
        exported = event.to_record()
        exported["payload"]["views"][TraceView.CANDIDATE.value]["session_started"] = False
        self.assertTrue(trace.verify_integrity())
        self.assertEqual(before, trace.canonical_spoken_history())

    def test_tamper_reorder_detection_and_stable_replay(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        self.next_question(trace, source)
        expected = trace.canonical_spoken_history()
        records = trace.export_records()
        reloaded = InterviewTraceV1.from_records(records)
        self.assertEqual(expected, reloaded.canonical_spoken_history())
        self.assertTrue(reloaded.verify_integrity())

        tampered = copy.deepcopy(records)
        index = next(i for i, record in enumerate(tampered) if record["event_type"] == TraceEventType.SPOKEN_QUESTION_COMMITTED.value)
        tampered[index]["payload"]["views"][TraceView.EVALUATOR.value]["question_text"] = "mutated"
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(tampered)
        reordered = copy.deepcopy(records)
        reordered[1], reordered[2] = reordered[2], reordered[1]
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(reordered)

    def test_import_star_smoke(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "from backend.services.interview_trace_v1 import *; assert InterviewTraceV1 and TraceEvent"],
            check=False, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
