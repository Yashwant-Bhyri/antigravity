"""Deterministic backend contract tests for the isolated InterviewTraceV1 module."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path

try:
    from backend.services.interview_trace_v1 import (
        InterviewTraceV1,
        PlaybackAckStatus,
        TraceEventType,
        TraceConflictError,
        TraceImmutableDecisionError,
        TraceIntegrityError,
        TraceInvariantError,
        TraceReferenceError,
        TraceStaleError,
        TraceView,
    )
except ModuleNotFoundError:  # direct execution from the backend directory
    from services.interview_trace_v1 import (
        InterviewTraceV1,
        PlaybackAckStatus,
        TraceEventType,
        TraceConflictError,
        TraceImmutableDecisionError,
        TraceIntegrityError,
        TraceInvariantError,
        TraceReferenceError,
        TraceStaleError,
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


def _rehash_record(record: dict[str, object]) -> None:
    body = copy.deepcopy(record)
    body.pop("event_hash", None)
    record["event_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _rehash_contract_record(record: dict[str, object]) -> None:
    record["decision_hash"] = InterviewTraceV1._decision_hash(
        str(record["event_type"]), record["payload"]
    )
    record["provenance_hash"] = InterviewTraceV1._provenance_hash(
        tuple(str(item) for item in record["causal_parent_ids"]), record["payload"]
    )
    _rehash_record(record)


def _rechain_records(records: list[dict[str, object]]) -> None:
    previous = "0" * 64
    for sequence, record in enumerate(records, start=1):
        record["sequence"] = sequence
        record["previous_event_hash"] = previous
        _rehash_record(record)
        previous = str(record["event_hash"])


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
            source_evidence_event_ids=[source["evidence"].event_id], idempotency_key="claim:1",
        )
        final = trace.record_final_evaluation_completed(
            evaluation_id="evaluation-1", report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[source["evidence"].event_id],
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

    def test_same_idempotency_key_with_changed_answer_is_conflict(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="first answer", idempotency_key="answer:same-key",
        )
        before = trace.export_records()
        with self.assertRaises(TraceConflictError):
            trace.record_answer_received(
                turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
                answer_text="changed answer", idempotency_key="answer:same-key",
            )
        self.assertEqual(before, trace.export_records())

    def test_alternate_key_logical_duplicates_are_conflicts(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        grant = trace.record_action_grant_selected(
            turn_id="turn-2", answer_version=1, opportunity_inventory_event_id=source["inventory"].event_id,
            opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, action="probe-boundary", idempotency_key="grant:alt",
        )
        trace.record_state_transition_validated(
            turn_id="turn-2", answer_version=1, decision="accepted", visible_route_commit_allowed=True,
            source_opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, action_grant_event_id=grant.event_id,
            idempotency_key="validation:alt",
        )
        materialized = trace.record_question_materialized(
            turn_id="turn-2", answer_version=1, question_id="question-turn-2",
            visible_text="What trade-off did you make in turn-2?", source_opportunity_id="opp-next",
            source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, action_grant_event_id=grant.event_id,
            idempotency_key="materialized:canonical",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_question_materialized(
                turn_id="turn-2", answer_version=1, question_id="question-turn-2",
                visible_text="changed materialization", source_opportunity_id="opp-next",
                source_evidence_event_ids=[source["semantic"].event_id],
                prior_spoken_question_event_id=opening["spoken"].event_id,
                action_grant_event_id=grant.event_id, idempotency_key="materialized:alternate",
            )
        prepared = trace.record_question_prepared(
            turn_id="turn-2", answer_version=1, question_id="question-turn-2",
            materialized_event_id=materialized.event_id, source_opportunity_id="opp-next",
            source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, idempotency_key="prepared:canonical",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_question_prepared(
                turn_id="turn-2", answer_version=1, question_id="question-turn-2",
                materialized_event_id=materialized.event_id, source_opportunity_id="opp-next",
                source_evidence_event_ids=[source["semantic"].event_id],
                prior_spoken_question_event_id=opening["spoken"].event_id,
                idempotency_key="prepared:alternate",
            )
        started = trace.record_question_delivery_started(
            turn_id="turn-2", answer_version=1, question_prepared_event_id=prepared.event_id,
            delivery_attempt_id="attempt-turn-2-1", idempotency_key="delivery-start:canonical",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_question_delivery_started(
                turn_id="turn-2", answer_version=1, question_prepared_event_id=prepared.event_id,
                delivery_attempt_id="attempt-turn-2-1", idempotency_key="delivery-start:alternate",
            )
        ack = trace.record_playback_acknowledged(
            turn_id="turn-2", answer_version=1, delivery_attempt_id="attempt-turn-2-1",
            delivery_started_event_id=started.event_id, client_ack=PlaybackAckStatus.COMPLETED,
            idempotency_key="playback-ack:canonical",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_playback_acknowledged(
                turn_id="turn-2", answer_version=1, delivery_attempt_id="attempt-turn-2-1",
                delivery_started_event_id=started.event_id,
                client_ack=PlaybackAckStatus.COMPLETED, idempotency_key="playback-ack:alternate",
            )
        spoken = trace.record_spoken_question_committed(
            turn_id="turn-2", answer_version=1, question_id="question-turn-2",
            visible_text="What trade-off did you make in turn-2?",
            question_materialized_event_id=materialized.event_id, playback_ack_event_id=ack.event_id,
            delivery_attempt_id="attempt-turn-2-1", prior_spoken_question_event_id=opening["spoken"].event_id,
            source_opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            idempotency_key="spoken:canonical",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_spoken_question_committed(
                turn_id="turn-2", answer_version=1, question_id="question-turn-2",
                visible_text="What trade-off did you make in turn-2?",
                question_materialized_event_id=materialized.event_id,
                playback_ack_event_id=ack.event_id, delivery_attempt_id="attempt-turn-2-1",
                prior_spoken_question_event_id=opening["spoken"].event_id,
                source_opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
                idempotency_key="spoken:alternate",
            )
        answer = trace.record_answer_received(
            turn_id="turn-2", answer_version=1, spoken_question_event_id=spoken.event_id,
            answer_text="canonical answer", idempotency_key="answer:canonical",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_answer_received(
                turn_id="turn-2", answer_version=1, spoken_question_event_id=spoken.event_id,
                answer_text="changed answer", idempotency_key="answer:alternate",
            )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-2", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"meaning": "canonical"}, idempotency_key="semantic:canonical",
        )
        with self.assertRaises(TraceImmutableDecisionError):
            trace.record_semantic_interpretation_finalized(
                turn_id="turn-2", answer_version=1, answer_event_id=answer.event_id,
                interpretation={"meaning": "changed"}, idempotency_key="semantic:alternate",
            )

    def test_playback_ack_requires_completed_and_is_exactly_once(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        grant = trace.record_action_grant_selected(
            turn_id="turn-2", answer_version=1, opportunity_inventory_event_id=source["inventory"].event_id,
            opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, action="probe-boundary", idempotency_key="grant:ack",
        )
        trace.record_state_transition_validated(
            turn_id="turn-2", answer_version=1, decision="accepted", visible_route_commit_allowed=True,
            source_opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, action_grant_event_id=grant.event_id,
            idempotency_key="validation:ack",
        )
        materialized = trace.record_question_materialized(
            turn_id="turn-2", answer_version=1, question_id="question-turn-2",
            visible_text="What trade-off did you make in turn-2?", source_opportunity_id="opp-next",
            source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, action_grant_event_id=grant.event_id,
            idempotency_key="materialized:ack",
        )
        prepared = trace.record_question_prepared(
            turn_id="turn-2", answer_version=1, question_id="question-turn-2",
            materialized_event_id=materialized.event_id, source_opportunity_id="opp-next",
            source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=opening["spoken"].event_id, idempotency_key="prepared:ack",
        )
        started = trace.record_question_delivery_started(
            turn_id="turn-2", answer_version=1, question_prepared_event_id=prepared.event_id,
            delivery_attempt_id="attempt-turn-2-1", idempotency_key="delivery:ack",
        )
        with self.assertRaises(TraceInvariantError):
            trace.record_playback_acknowledged(
                turn_id="turn-2", answer_version=1, delivery_attempt_id="attempt-turn-2-1",
                delivery_started_event_id=started.event_id, client_ack="playback_failed",
                idempotency_key="ack:negative",
            )
        ack = trace.record_playback_acknowledged(
            turn_id="turn-2", answer_version=1, delivery_attempt_id="attempt-turn-2-1",
            delivery_started_event_id=started.event_id,
            client_ack=PlaybackAckStatus.COMPLETED, idempotency_key="ack:positive",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_playback_acknowledged(
                turn_id="turn-2", answer_version=1, delivery_attempt_id="attempt-turn-2-1",
                delivery_started_event_id=started.event_id,
                client_ack=PlaybackAckStatus.COMPLETED, idempotency_key="ack:alternate",
            )
        self.assertEqual(
            1,
            sum(event.event_id == ack.event_id for event in trace.events),
        )

    def test_failed_public_operations_are_atomic(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        before_events = trace.export_records()
        before_turns = copy.deepcopy(trace._turns)

        trace._clock = lambda: (_ for _ in ()).throw(RuntimeError("clock failed"))
        with self.assertRaises(RuntimeError):
            trace.record_state_transition_validated(
                turn_id="turn-clock", answer_version=1, decision="accepted",
                visible_route_commit_allowed=True, source_opportunity_id="opening",
                source_evidence_event_ids=[opening["session"].event_id], idempotency_key="clock-failure",
            )
        self.assertEqual(before_events, trace.export_records())
        self.assertEqual(before_turns, trace._turns)

        trace._clock = _Clock()
        with self.assertRaises(TraceInvariantError):
            trace.record_answer_received(
                turn_id="turn-1", answer_version=2, spoken_question_event_id=opening["spoken"].event_id,
                answer_text="", idempotency_key="empty-answer",
            )
        self.assertEqual(before_events, trace.export_records())
        self.assertEqual(before_turns, trace._turns)

    def test_domain_rejection_is_receipt_and_validation_error_is_not_event(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        before = len(trace.events)
        rejected = trace.record_state_transition_validated(
            turn_id="turn-rejected", answer_version=1, decision="rejected",
            visible_route_commit_allowed=True, source_opportunity_id="opening",
            source_evidence_event_ids=[opening["session"].event_id], reason="not eligible",
            idempotency_key="validation:domain-rejected",
        )
        self.assertFalse(rejected.accepted)
        self.assertIsNotNone(rejected.event)
        self.assertEqual(len(trace.events), before + 1)
        with self.assertRaises(TraceInvariantError):
            trace.record_question_materialized(
                turn_id="turn-rejected", answer_version=1, question_id="q",
                visible_text="must not show", source_opportunity_id="opening",
                source_evidence_event_ids=[opening["session"].event_id], idempotency_key="materialized:no",
            )
        self.assertEqual(len(trace.events), before + 1)

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

    def test_import_rejects_unknown_future_duplicate_and_tampered_lineage(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        records = trace.export_records()

        future_parent = copy.deepcopy(records)
        future_parent[-1]["causal_parent_ids"].append("future-event")
        _rehash_record(future_parent[-1])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(future_parent)

        duplicate_parent = copy.deepcopy(records)
        duplicate_parent[-1]["causal_parent_ids"].append(duplicate_parent[-1]["causal_parent_ids"][0])
        _rehash_record(duplicate_parent[-1])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(duplicate_parent)

        unknown_type = copy.deepcopy(records)
        unknown_type[-1]["event_type"] = "unknown_event_type"
        _rehash_record(unknown_type[-1])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(unknown_type)

        decision_tamper = copy.deepcopy(records)
        decision_tamper[-1]["decision_hash"] = "tampered-decision"
        _rehash_record(decision_tamper[-1])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(decision_tamper)

        provenance_tamper = copy.deepcopy(records)
        provenance_tamper[-1]["provenance_hash"] = "tampered-provenance"
        _rehash_record(provenance_tamper[-1])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(provenance_tamper)

        missing_genesis = copy.deepcopy(records[1:])
        _rechain_records(missing_genesis)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(missing_genesis)

        bad_epoch = copy.deepcopy(records)
        bad_epoch[-1]["runtime_epoch"] = 99
        _rehash_record(bad_epoch[-1])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(bad_epoch)

        bad_schema = copy.deepcopy(records)
        bad_schema[0]["schema_version"] = "interview_trace_v0"
        _rehash_record(bad_schema[0])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(bad_schema)

        bad_payload_schema = copy.deepcopy(records)
        bad_payload_schema[0]["payload_schema_version"] = "payload_v0"
        _rehash_record(bad_payload_schema[0])
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(bad_payload_schema)

    def test_import_rejects_rehashed_playback_and_report_lineage_tampering(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        records = trace.export_records()
        ack_index = next(
            index for index, record in enumerate(records)
            if record["event_type"] == TraceEventType.PLAYBACK_ACKNOWLEDGED.value
        )
        negative_ack = copy.deepcopy(records)
        ack = negative_ack[ack_index]
        ack["payload"]["views"][TraceView.EVALUATOR.value]["client_ack"] = "playback_failed"
        ack["payload"]["views"][TraceView.EVALUATOR.value]["acknowledged"] = False
        ack["payload"]["views"][TraceView.ACTOR.value]["acknowledged"] = False
        ack["payload"]["views"][TraceView.INTERVIEWER.value]["acknowledged"] = False
        ack["payload"]["views"][TraceView.CANDIDATE.value]["acknowledged"] = False
        _rehash_contract_record(ack)
        _rechain_records(negative_ack)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(negative_ack)

        source = self.answer_inventory(trace, opening)
        claim = trace.record_report_claim_emitted(
            claim_id="claim-tamper",
            claim_text="grounded",
            source_evidence_event_ids=[source["evidence"].event_id],
            idempotency_key="claim:tamper",
        )
        report_records = trace.export_records()
        claim_record = next(record for record in report_records if record["event_id"] == claim.event_id)
        claim_record["causal_parent_ids"] = [opening["session"].event_id]
        claim_record["payload"]["views"][TraceView.EVALUATOR.value]["source_evidence_event_ids"] = [opening["session"].event_id]
        _rehash_contract_record(claim_record)
        _rechain_records(report_records)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(report_records)

        final = trace.record_final_evaluation_completed(
            evaluation_id="final-tamper",
            report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[source["evidence"].event_id],
            evaluation_summary={},
            idempotency_key="final:tamper",
        )
        final_records = trace.export_records()
        final_record = next(record for record in final_records if record["event_id"] == final.event_id)
        final_record["causal_parent_ids"] = [claim.event_id, source["semantic"].event_id]
        final_record["payload"]["views"][TraceView.EVALUATOR.value]["evidence_event_ids"] = [source["semantic"].event_id]
        _rehash_contract_record(final_record)
        _rechain_records(final_records)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(final_records)

    def test_import_rejects_materialization_when_validation_disallows_visible_commit(self) -> None:
        trace = self.trace()
        self.opening(trace)
        records = trace.export_records()
        validation = next(
            record
            for record in records
            if record["event_type"] == TraceEventType.STATE_TRANSITION_VALIDATED.value
            and record["payload"]["views"][TraceView.EVALUATOR.value].get("validation_status") == "accepted"
        )
        for view_name in (
            TraceView.INTERVIEWER.value,
            TraceView.EVALUATOR.value,
            TraceView.OPERATOR.value,
        ):
            validation["payload"]["views"][view_name]["visible_route_commit_allowed"] = False
        _rehash_contract_record(validation)
        _rechain_records(records)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(records)

    def test_import_rejects_rehashed_cross_view_validation_status_mismatch(self) -> None:
        trace = self.trace()
        self.opening(trace)
        records = trace.export_records()
        validation = next(
            record
            for record in records
            if record["event_type"] == TraceEventType.STATE_TRANSITION_VALIDATED.value
            and record["payload"]["views"][TraceView.EVALUATOR.value].get("validation_status") == "accepted"
        )
        for view_name in (TraceView.INTERVIEWER.value, TraceView.OPERATOR.value):
            validation["payload"]["views"][view_name]["validation_status"] = "rejected"
        _rehash_contract_record(validation)
        _rechain_records(records)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(records)

    def test_import_rejects_ack_failure_conflict_even_when_spoken_truth_follows(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        base_records = trace.export_records()
        ack_index = next(
            index
            for index, record in enumerate(base_records)
            if record["event_type"] == TraceEventType.PLAYBACK_ACKNOWLEDGED.value
        )
        started_event_id = next(
            record["event_id"]
            for record in base_records[:ack_index]
            if record["event_type"] == TraceEventType.QUESTION_DELIVERY_STARTED.value
        )
        attempt_id = base_records[ack_index]["payload"]["views"][TraceView.EVALUATOR.value]["delivery_attempt_id"]

        def conflicting_records(insert_at: int) -> list[dict[str, object]]:
            records = copy.deepcopy(base_records)
            failure = copy.deepcopy(records[ack_index])
            failure["event_id"] = "delivery-failure-conflict"
            failure["event_type"] = TraceEventType.DELIVERY_FAILED.value
            failure["causal_parent_ids"] = [started_event_id]
            failure["idempotency_key"] = "delivery-failure-conflict"
            failure["payload"]["views"] = {
                TraceView.CANDIDATE.value: {
                    "delivery_attempt_id": attempt_id,
                    "delivery_failed": True,
                },
                TraceView.ACTOR.value: {
                    "delivery_attempt_id": attempt_id,
                    "delivery_failed": True,
                    "retryable": True,
                },
                TraceView.INTERVIEWER.value: {
                    "delivery_attempt_id": attempt_id,
                    "delivery_failed": True,
                },
                TraceView.EVALUATOR.value: {
                    "delivery_attempt_id": attempt_id,
                    "delivery_failed": True,
                    "retryable": True,
                },
                TraceView.OPERATOR.value: {
                    "delivery_attempt_id": attempt_id,
                    "delivery_failed": True,
                    "retryable": True,
                    "reason": "late audio error",
                },
            }
            _rehash_contract_record(failure)
            records.insert(insert_at, failure)
            _rechain_records(records)
            return records

        # The original spoken event remains after the injected failure in
        # both cases, so a delivery contradiction cannot be hidden by later
        # candidate-visible truth.
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(conflicting_records(ack_index + 1))
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(conflicting_records(ack_index))
        self.assertTrue(any(record["event_type"] == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for record in base_records))
        self.assertEqual(opening["spoken"].event_id, next(
            record["event_id"]
            for record in base_records
            if record["event_type"] == TraceEventType.SPOKEN_QUESTION_COMMITTED.value
        ))

    def test_grant_validation_and_materialization_require_one_immediate_prior_lineage(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        second = self.next_question(trace, source, turn_id="turn-2")
        older_prior = opening["spoken"].event_id
        current_prior = second["spoken"].event_id

        with self.assertRaises(TraceInvariantError):
            trace.record_action_grant_selected(
                turn_id="turn-3", answer_version=1,
                opportunity_inventory_event_id=source["inventory"].event_id,
                opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
                prior_spoken_question_event_id=older_prior, action="probe-boundary",
                idempotency_key="grant:turn-3:old-prior",
            )

        grant = trace.record_action_grant_selected(
            turn_id="turn-3", answer_version=1,
            opportunity_inventory_event_id=source["inventory"].event_id,
            opportunity_id="opp-next", source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=current_prior, action="probe-boundary",
            idempotency_key="grant:turn-3:current-prior",
        )
        with self.assertRaises(TraceInvariantError):
            trace.record_state_transition_validated(
                turn_id="turn-3", answer_version=1, decision="accepted",
                visible_route_commit_allowed=True, source_opportunity_id="opp-next",
                source_evidence_event_ids=[source["semantic"].event_id],
                prior_spoken_question_event_id=older_prior, action_grant_event_id=grant.event_id,
                idempotency_key="validation:turn-3:old-prior",
            )
        validation = trace.record_state_transition_validated(
            turn_id="turn-3", answer_version=1, decision="accepted",
            visible_route_commit_allowed=True, source_opportunity_id="opp-next",
            source_evidence_event_ids=[source["semantic"].event_id],
            prior_spoken_question_event_id=current_prior, action_grant_event_id=grant.event_id,
            idempotency_key="validation:turn-3:current-prior",
        )
        with self.assertRaises(TraceInvariantError):
            trace.record_question_materialized(
                turn_id="turn-3", answer_version=1, question_id="question-turn-3",
                visible_text="How did you measure it?", source_opportunity_id="opp-next",
                source_evidence_event_ids=[source["semantic"].event_id],
                prior_spoken_question_event_id=older_prior, action_grant_event_id=grant.event_id,
                idempotency_key="materialized:turn-3:old-prior",
            )
        self.assertEqual(validation.event_id, trace._turns["turn-3"].validation_event_id)

        valid = self.next_question(trace, source, turn_id="turn-4")
        valid_records = trace.export_records()
        for event_type in (
            TraceEventType.ACTION_GRANT_SELECTED.value,
            TraceEventType.STATE_TRANSITION_VALIDATED.value,
            TraceEventType.QUESTION_MATERIALIZED.value,
        ):
            records = copy.deepcopy(valid_records)
            target = next(
                record
                for record in records
                if record["turn_id"] == "turn-4"
                and record["event_type"] == event_type
            )
            target["payload"]["views"][TraceView.EVALUATOR.value]["prior_spoken_question_event_id"] = older_prior
            _rehash_contract_record(target)
            _rechain_records(records)
            with self.assertRaises(TraceIntegrityError):
                InterviewTraceV1.from_records(records)
        self.assertEqual("turn-4", valid["spoken"].turn_id)

    def test_unverified_import_is_tainted_read_only_until_successful_verification(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        records = trace.export_records()
        unverified = InterviewTraceV1.from_records(records, verify=False)
        self.assertFalse(unverified.is_authoritative)
        self.assertEqual(records, unverified.export_records())
        with self.assertRaises(TraceIntegrityError):
            unverified.project(TraceView.CANDIDATE)
        with self.assertRaises(TraceIntegrityError):
            unverified.canonical_spoken_history()
        with self.assertRaises(TraceIntegrityError):
            unverified.record_answer_received(
                turn_id="turn-1", answer_version=1,
                spoken_question_event_id=opening["spoken"].event_id,
                answer_text="must not append", idempotency_key="answer:tainted",
            )
        self.assertTrue(unverified.verify_integrity())
        self.assertTrue(unverified.is_authoritative)
        self.assertEqual(trace.canonical_spoken_history(), unverified.canonical_spoken_history())

    def test_import_re_normalizes_opportunity_inventory_and_requires_typed_evidence(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        base_records = trace.export_records()

        def assert_inventory_rejected(mutator: Callable[[dict[str, object], dict[str, object]], None]) -> None:
            records = copy.deepcopy(base_records)
            inventory = next(
                record
                for record in records
                if record["event_id"] == source["inventory"].event_id
            )
            mutator(inventory, records[0])
            _rehash_contract_record(inventory)
            _rechain_records(records)
            with self.assertRaises(TraceIntegrityError):
                InterviewTraceV1.from_records(records)

        def missing_kind(inventory: dict[str, object], _session: dict[str, object]) -> None:
            admitted = inventory["payload"]["views"][TraceView.EVALUATOR.value]["admitted_candidates"]
            del admitted[0]["kind"]

        def duplicate_id(inventory: dict[str, object], _session: dict[str, object]) -> None:
            views = inventory["payload"]["views"][TraceView.EVALUATOR.value]
            views["excluded_candidates"][0]["opportunity_id"] = views["admitted_candidates"][0]["opportunity_id"]

        def unknown_evidence(inventory: dict[str, object], _session: dict[str, object]) -> None:
            admitted = inventory["payload"]["views"][TraceView.EVALUATOR.value]["admitted_candidates"]
            admitted[0]["evidence_event_ids"] = ["not-an-event"]

        def wrong_evidence_type(inventory: dict[str, object], session: dict[str, object]) -> None:
            admitted = inventory["payload"]["views"][TraceView.EVALUATOR.value]["admitted_candidates"]
            admitted[0]["evidence_event_ids"] = [session["event_id"]]

        assert_inventory_rejected(missing_kind)
        assert_inventory_rejected(duplicate_id)
        assert_inventory_rejected(unknown_evidence)
        assert_inventory_rejected(wrong_evidence_type)

    def test_verified_import_is_idempotent_for_value_key_and_mixed_redaction(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1,
            spoken_question_event_id=opening["spoken"].event_id,
            answer_text="redaction round trip", idempotency_key="answer:redaction-round-trip",
        )
        trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={
                "connection": "postgresql://user:password@example.test/db",
                "api_key": "sk-secret-value",
                "nested": {
                    "connection": "postgresql://nested:password@example.test/db",
                    "headers": [
                        {"access_token": "token-secret-value"},
                        {"safe": "keep"},
                    ],
                },
            },
            idempotency_key="semantic:redaction-round-trip",
        )
        records = trace.export_records()
        semantic_record = next(
            record
            for record in records
            if record["event_type"] == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value
        )
        self.assertEqual(
            [
                "views.evaluator.interpretation.api_key",
                "views.evaluator.interpretation.connection",
                "views.evaluator.interpretation.nested.connection",
                "views.evaluator.interpretation.nested.headers[0].access_token",
            ],
            semantic_record["redaction"]["redacted_paths"],
        )
        reloaded = InterviewTraceV1.from_records(records)
        self.assertTrue(reloaded.is_authoritative)
        self.assertEqual(records, reloaded.export_records())

    def test_import_accepts_reordered_mixed_redaction_keys_without_rehash(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1,
            spoken_question_event_id=opening["spoken"].event_id,
            answer_text="redaction key order", idempotency_key="answer:redaction-key-order",
        )
        trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={
                "connection": "postgresql://user:password@example.test/db",
                "api_key": "sk-secret-value",
                "nested": {
                    "connection": "postgresql://nested:password@example.test/db",
                    "headers": [{"access_token": "token-secret-value"}],
                },
            },
            idempotency_key="semantic:redaction-key-order",
        )
        records = trace.export_records()
        target = next(
            record
            for record in records
            if record["event_type"] == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value
        )
        original_hashes = (
            target["event_hash"],
            target["decision_hash"],
            target["provenance_hash"],
        )
        interpretation = target["payload"]["views"][TraceView.EVALUATOR.value]["interpretation"]
        nested = interpretation["nested"]
        target["payload"]["views"][TraceView.EVALUATOR.value]["interpretation"] = {
            "nested": {
                "headers": nested["headers"],
                "connection": nested["connection"],
            },
            "api_key": interpretation["api_key"],
            "connection": interpretation["connection"],
        }
        self.assertEqual(original_hashes[0], target["event_hash"])
        self.assertEqual(original_hashes[1], target["decision_hash"])
        self.assertEqual(original_hashes[2], target["provenance_hash"])
        reloaded = InterviewTraceV1.from_records(records)
        self.assertEqual(records, reloaded.export_records())

    def test_import_rejects_missing_or_fabricated_value_redaction_metadata(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1,
            spoken_question_event_id=opening["spoken"].event_id,
            answer_text="redaction metadata", idempotency_key="answer:redaction-metadata",
        )
        trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"connection": "postgresql://user:password@example.test/db"},
            idempotency_key="semantic:redaction-metadata",
        )
        base_records = trace.export_records()

        for redacted_paths in ([], ["views.evaluator.interpretation.not_connection"]):
            records = copy.deepcopy(base_records)
            target = next(
                record
                for record in records
                if record["event_type"] == TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value
            )
            target["redaction"]["redacted_paths"] = redacted_paths
            _rechain_records(records)
            with self.assertRaises(TraceIntegrityError):
                InterviewTraceV1.from_records(records)

    def test_import_recomputes_redaction_metadata(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1,
            spoken_question_event_id=opening["spoken"].event_id,
            answer_text="redaction metadata", idempotency_key="answer:redaction-metadata",
        )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"api_key": "sk-secret-value", "meaning": "safe"},
            idempotency_key="semantic:redaction-metadata",
        )
        records = trace.export_records()
        target = next(record for record in records if record["event_id"] == semantic.event_id)
        target["redaction"]["redacted_paths"] = ["bogus.path"]
        _rechain_records(records)
        with self.assertRaises(TraceIntegrityError):
            InterviewTraceV1.from_records(records)

    def test_candidate_projection_excludes_preplayback_text_and_internal_metadata(self) -> None:
        trace = self.trace()
        self.opening(trace)
        candidate = trace.project(TraceView.CANDIDATE)
        actor = trace.project(TraceView.ACTOR)
        for projection in (candidate, actor):
            self.assertTrue(projection)
            for item in projection:
                self.assertNotIn("producer", item)
                self.assertNotIn("runtime_epoch", item)
                self.assertNotIn("occurred_at_ms", item)
                self.assertNotIn("recorded_at_ms", item)
        self.assertFalse(any(item["event_type"] in {
            TraceEventType.QUESTION_PREPARED.value,
            TraceEventType.QUESTION_MATERIALIZED.value,
        } for item in candidate))
        spoken_items = [
            item for item in candidate
            if item["event_type"] == TraceEventType.SPOKEN_QUESTION_COMMITTED.value
        ]
        self.assertTrue(spoken_items)
        self.assertTrue(any(item["payload"].get("question_text") for item in spoken_items))
        evaluator = trace.project(TraceView.EVALUATOR)
        self.assertTrue(any(
            item["event_type"] == TraceEventType.QUESTION_MATERIALIZED.value
            and "question_text" in item["payload"]
            for item in evaluator
        ))

    def test_nonzero_initial_epoch_and_rejected_telemetry_reload_without_ghost_turn(self) -> None:
        nonzero = InterviewTraceV1("nonzero-epoch", runtime_epoch=4, clock=_Clock())
        self.assertTrue(nonzero.verify_integrity())
        reloaded_nonzero = InterviewTraceV1.from_records(nonzero.export_records(), clock=_Clock())
        self.assertEqual(4, reloaded_nonzero.runtime_epoch)

        trace = self.trace()
        opening = self.opening(trace)
        rejected = trace.record_state_transition_validated(
            turn_id="ghost-turn",
            answer_version=1,
            decision="rejected",
            visible_route_commit_allowed=True,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[opening["session"].event_id],
            reason="not eligible",
            idempotency_key="validation:ghost-turn",
        )
        self.assertFalse(rejected.accepted)
        reloaded = InterviewTraceV1.from_records(trace.export_records(), clock=_Clock())
        self.assertNotIn("ghost-turn", trace._turns)
        self.assertNotIn("ghost-turn", reloaded._turns)
        self.assertEqual(trace._turns, reloaded._turns)

    def test_new_turn_future_answer_version_is_rejected_without_ledger(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        rejected = trace.record_state_transition_validated(
            turn_id="future-turn",
            answer_version=3,
            decision="accepted",
            visible_route_commit_allowed=True,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[opening["session"].event_id],
            idempotency_key="validation:future-turn",
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual("answer_version_gap", rejected.reason)
        self.assertNotIn("future-turn", trace._turns)

    def test_session_and_epoch_retries_are_exactly_once(self) -> None:
        trace = self.trace()
        started = trace.start_session()
        self.assertTrue(started.idempotent)
        advanced = trace.advance_runtime_epoch(1)
        repeated = trace.advance_runtime_epoch(1)
        self.assertTrue(repeated.idempotent)
        self.assertEqual(advanced.event_id, repeated.event_id)
        self.assertTrue(trace.start_session().idempotent)
        with self.assertRaises(TraceConflictError):
            trace.start_session(producer="different.session", idempotency_key="alternate-session-key")

    def test_report_and_final_evaluation_require_evidence_lineage_and_are_exactly_once(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        with self.assertRaises(TraceReferenceError):
            trace.record_report_claim_emitted(
                claim_id="bad-claim", claim_text="bad", source_evidence_event_ids=[opening["session"].event_id],
                idempotency_key="claim:bad-source",
            )
        claim = trace.record_report_claim_emitted(
            claim_id="claim-exact", claim_text="grounded", source_evidence_event_ids=[source["evidence"].event_id],
            idempotency_key="claim:exact",
        )
        with self.assertRaises(TraceReferenceError):
            trace.record_final_evaluation_completed(
                evaluation_id="bad-final", report_claim_event_ids=[claim.event_id],
                evidence_event_ids=[source["semantic"].event_id], evaluation_summary={}, idempotency_key="final:bad",
            )
        final = trace.record_final_evaluation_completed(
            evaluation_id="final-exact", report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[source["evidence"].event_id], evaluation_summary={}, idempotency_key="final:exact",
        )
        with self.assertRaises(TraceConflictError):
            trace.record_report_claim_emitted(
                claim_id="claim-exact", claim_text="changed", source_evidence_event_ids=[source["evidence"].event_id],
                idempotency_key="claim:alternate",
            )
        with self.assertRaises(TraceConflictError):
            trace.record_final_evaluation_completed(
                evaluation_id="final-other", report_claim_event_ids=[claim.event_id],
                evidence_event_ids=[source["evidence"].event_id], evaluation_summary={"changed": True},
                idempotency_key="final:alternate",
            )
        self.assertEqual(final.event_id, trace._final_evaluation_event_id)

    def test_report_and_final_evaluation_require_current_runtime_epoch(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        trace.advance_runtime_epoch(1)
        with self.assertRaises(TraceStaleError):
            trace.record_report_claim_emitted(
                claim_id="stale-claim", claim_text="stale", source_evidence_event_ids=[source["evidence"].event_id],
                runtime_epoch=0, idempotency_key="claim:stale",
            )

    def test_redaction_covers_prompt_and_secret_value_forms(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=opening["spoken"].event_id,
            answer_text="redaction", idempotency_key="answer:redaction-new",
        )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={
                "prompt": "TOP-SECRET-PROMPT",
                "developer_message": "HIDDEN-INSTRUCTION",
                "accessToken": "ghp_1234567890abcdef",
                "connection": "postgresql://user:password@example.test/db",
            }, idempotency_key="semantic:redaction-new",
        )
        interpretation = semantic.event.payload["views"][TraceView.EVALUATOR.value]["interpretation"]
        self.assertEqual(interpretation["prompt"], "[REDACTED]")
        self.assertEqual(interpretation["developer_message"], "[REDACTED]")
        self.assertEqual(interpretation["accessToken"], "[REDACTED]")
        self.assertEqual(interpretation["connection"], "[REDACTED]")

    def test_candidate_and_actor_projection_do_not_expose_global_sequence(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        candidate = trace.project(TraceView.CANDIDATE)
        actor = trace.project(TraceView.ACTOR)
        self.assertTrue(candidate)
        self.assertTrue(actor)
        self.assertTrue(all("sequence" not in item for item in candidate))
        self.assertTrue(all("sequence" not in item for item in actor))
        self.assertEqual(opening["session"].event_id, candidate[0]["event_id"])

    def test_reload_rebuilds_indexes_and_projections_exactly(self) -> None:
        trace = self.trace()
        opening = self.opening(trace)
        source = self.answer_inventory(trace, opening)
        self.next_question(trace, source)
        trace.advance_runtime_epoch(1)
        reloaded = InterviewTraceV1.from_records(trace.export_records())
        self.assertEqual(trace.runtime_epoch, reloaded.runtime_epoch)
        self.assertEqual(trace.last_spoken_question_event_id, reloaded.last_spoken_question_event_id)
        self.assertEqual(trace.canonical_spoken_history(), reloaded.canonical_spoken_history())
        self.assertEqual(trace.project(TraceView.CANDIDATE), reloaded.project(TraceView.CANDIDATE))
        self.assertEqual(trace.project(TraceView.ACTOR), reloaded.project(TraceView.ACTOR))
        self.assertEqual(trace._turns, reloaded._turns)

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
