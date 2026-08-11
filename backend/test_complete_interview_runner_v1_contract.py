"""Focused boundary tests for CompleteInterviewRunnerV1 shadow evidence."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from backend.services.complete_interview_runner_v1 import (
        BrowserPlaybackAdapter,
        CompleteInterviewRunnerConfig,
        CompleteInterviewRunnerV1,
        DeterministicTTSAdapter,
        IsolatedSessionStore,
        IsolatedTelemetrySink,
        ProductionProviderAttemptLedger,
        ProviderCallCapExceeded,
        TraceEventType,
    )
    from backend.services.interview_trace_v1 import (
        InterviewTraceV1,
        TraceInvariantError,
        TraceReferenceError,
        TraceView,
    )
except ModuleNotFoundError:  # direct execution from the backend directory
    from services.complete_interview_runner_v1 import (
        BrowserPlaybackAdapter,
        CompleteInterviewRunnerConfig,
        CompleteInterviewRunnerV1,
        DeterministicTTSAdapter,
        IsolatedSessionStore,
        IsolatedTelemetrySink,
        ProductionProviderAttemptLedger,
        ProviderCallCapExceeded,
    )
    from services.interview_trace_v1 import (
        InterviewTraceV1,
        TraceEventType,
        TraceInvariantError,
        TraceReferenceError,
        TraceView,
    )


class CompleteInterviewRunnerV1ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_attempt_ledger_caps_before_second_provider_request(self) -> None:
        class FakeCompletions:
            def __init__(self) -> None:
                self.calls = 0

            async def create(self, **_: object) -> dict[str, str]:
                self.calls += 1
                return {"ok": "provider-response"}

        class FakeRouter:
            tier = "small"
            model = "test/model"

            def __init__(self) -> None:
                completions = FakeCompletions()
                self.client = type("Client", (), {})()
                self.client.chat = type("Chat", (), {})()
                self.client.chat.completions = completions

        router = FakeRouter()
        ledger = ProductionProviderAttemptLedger(cap=1)
        ledger.instrument_router(router)
        result = await router.client.chat.completions.create(model="test/model", max_tokens=1)
        self.assertEqual(result, {"ok": "provider-response"})
        with self.assertRaises(ProviderCallCapExceeded):
            await router.client.chat.completions.create(model="test/model", max_tokens=1)
        self.assertEqual(router.client.chat.completions.calls, 1)
        self.assertEqual(ledger.to_dict()["attempt_count"], 1)
        self.assertEqual(ledger.to_dict()["cap_blocked_attempts"], 1)
        ledger.restore()

    async def test_production_mode_credential_preflight_is_zero_provider_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="runner-production-preflight-") as directory:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False), patch(
                "backend.services.local_experiment_credentials.load_local_experiment_credentials",
                return_value={"loaded": False, "reason": "local_experiment_env_missing"},
            ):
                result = await CompleteInterviewRunnerV1(
                    CompleteInterviewRunnerConfig(
                        semantic_provider_mode="production",
                        artifact_dir=Path(directory),
                    )
                ).run()
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.blocker["layer"], "production_semantic_preflight")
            self.assertEqual(result.provider_runtime["attempt_count"], 0)
            canonical_path = Path(directory) / "complete_interview_runner_v1_canonical_trace.json"
            records = json.loads(canonical_path.read_text(encoding="utf-8"))
            self.assertTrue(InterviewTraceV1.from_records(records).verify_integrity())

    def _opening(self, session_id: str = "runner-contract") -> tuple[InterviewTraceV1, dict[str, object]]:
        trace = InterviewTraceV1(session_id)
        session = trace.events[0]
        validation = trace.record_state_transition_validated(
            turn_id="turn-1",
            answer_version=1,
            decision="accepted",
            visible_route_commit_allowed=True,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key="validation:turn-1",
        )
        materialized = trace.record_question_materialized(
            turn_id="turn-1",
            answer_version=1,
            question_id="question-turn-1",
            visible_text="Tell me about the work.",
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key="materialized:turn-1",
            route_kind="warm_open",
        )
        prepared = trace.record_question_prepared(
            turn_id="turn-1",
            answer_version=1,
            question_id="question-turn-1",
            materialized_event_id=materialized.event_id,
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[session.event_id],
            idempotency_key="prepared:turn-1",
        )
        return trace, {
            "session": session,
            "validation": validation.event,
            "materialized": materialized.event,
            "prepared": prepared.event,
        }

    async def test_no_ack_blocks_spoken_truth_and_does_not_start_candidate_turn(self) -> None:
        with tempfile.TemporaryDirectory(prefix="runner-contract-no-ack-") as directory:
            result = await CompleteInterviewRunnerV1(
                CompleteInterviewRunnerConfig(
                    playback_failure_modes={1: "no_ack"},
                    artifact_dir=Path(directory),
                )
            ).run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.turns_committed, 0)
        event_types = [item["event_type"] for item in result.trace_records]
        self.assertIn(TraceEventType.DELIVERY_FAILED.value, event_types)
        self.assertNotIn(TraceEventType.SPOKEN_QUESTION_COMMITTED.value, event_types)
        self.assertNotIn(TraceEventType.ANSWER_RECEIVED.value, event_types)
        self.assertNotIn(TraceEventType.EVIDENCE_STATE_UPDATED.value, event_types)
        self.assertTrue(InterviewTraceV1.from_records(result.trace_records).verify_integrity())

    async def test_tts_failure_is_recorded_as_failed_delivery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="runner-contract-tts-") as directory:
            result = await CompleteInterviewRunnerV1(
                CompleteInterviewRunnerConfig(artifact_dir=Path(directory)),
                tts_adapter=DeterministicTTSAdapter(fail_on_calls={1}),
            ).run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.turns_committed, 0)
        self.assertIn(
            TraceEventType.DELIVERY_FAILED.value,
            [item["event_type"] for item in result.trace_records],
        )
        self.assertNotIn(
            TraceEventType.SPOKEN_QUESTION_COMMITTED.value,
            [item["event_type"] for item in result.trace_records],
        )

    async def test_stale_epoch_ack_is_rejected_then_new_attempt_can_ack(self) -> None:
        trace, opening = self._opening("runner-stale")
        adapter = BrowserPlaybackAdapter()
        first = await adapter.deliver(
            trace=trace,
            turn_id="turn-1",
            answer_version=1,
            prepared_event_id=opening["prepared"].event_id,
            runtime_epoch=0,
            turn_number=1,
            attempt_number=1,
            mode="stale_epoch",
        )
        self.assertFalse(first.acknowledged)
        self.assertFalse(any(event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for event in trace.events))
        self.assertTrue(any(
            event.event_type == TraceEventType.STATE_TRANSITION_VALIDATED.value
            and event.payload["views"][TraceView.EVALUATOR.value].get("validation_status") == "rejected"
            for event in trace.events
        ))
        second = await adapter.deliver(
            trace=trace,
            turn_id="turn-1",
            answer_version=1,
            prepared_event_id=opening["prepared"].event_id,
            runtime_epoch=0,
            turn_number=1,
            attempt_number=2,
            mode="ack",
        )
        self.assertTrue(second.acknowledged)
        ack = next(event for event in reversed(trace.events) if event.event_type == TraceEventType.PLAYBACK_ACKNOWLEDGED.value)
        spoken = trace.record_spoken_question_committed(
            turn_id="turn-1",
            answer_version=1,
            question_id="question-turn-1",
            visible_text="Tell me about the work.",
            question_materialized_event_id=opening["materialized"].event_id,
            playback_ack_event_id=ack.event_id,
            delivery_attempt_id="delivery-turn-1-2",
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[opening["session"].event_id],
            idempotency_key="spoken:turn-1:retry",
        )
        self.assertTrue(spoken.accepted)
        self.assertTrue(trace.verify_integrity())

    def test_semantic_timeout_shadow_cannot_replace_fallback_or_create_truth(self) -> None:
        trace, opening = self._opening("runner-semantic-timeout")
        # Complete the delivery boundary synchronously for this focused trace.
        started = trace.record_question_delivery_started(
            turn_id="turn-1",
            answer_version=1,
            question_prepared_event_id=opening["prepared"].event_id,
            delivery_attempt_id="delivery-turn-1-1",
            idempotency_key="delivery-start:turn-1",
        )
        ack = trace.record_playback_acknowledged(
            turn_id="turn-1",
            answer_version=1,
            delivery_attempt_id="delivery-turn-1-1",
            delivery_started_event_id=started.event_id,
            idempotency_key="ack:turn-1",
        )
        spoken = trace.record_spoken_question_committed(
            turn_id="turn-1",
            answer_version=1,
            question_id="question-turn-1",
            visible_text="Tell me about the work.",
            question_materialized_event_id=opening["materialized"].event_id,
            playback_ack_event_id=ack.event_id,
            delivery_attempt_id="delivery-turn-1-1",
            source_opportunity_id="opening-question",
            source_evidence_event_ids=[opening["session"].event_id],
            idempotency_key="spoken:turn-1",
        )
        answer = trace.record_answer_received(
            turn_id="turn-1",
            answer_version=1,
            spoken_question_event_id=spoken.event_id,
            answer_text="I owned the analysis boundary.",
            idempotency_key="answer:turn-1",
        )
        fallback = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1",
            answer_version=1,
            answer_event_id=answer.event_id,
            interpretation={"status": "semantic_timeout_fallback", "control_only": True},
            idempotency_key="semantic-final:fallback",
        )
        shadow = trace.record_semantic_interpretation_shadow(
            turn_id="turn-1",
            answer_version=1,
            answer_event_id=answer.event_id,
            finalized_event_id=fallback.event_id,
            interpretation={"status": "late_provider_result", "claim": "must_not_replace"},
            disagreement={"kind": "semantic_timeout"},
            idempotency_key="semantic-shadow:late",
        )
        self.assertTrue(shadow.accepted)
        evaluator = next(event for event in trace.events if event.event_id == fallback.event_id).payload["views"][TraceView.EVALUATOR.value]
        self.assertEqual(evaluator["interpretation"]["status"], "semantic_timeout_fallback")
        inventory = trace.record_opportunity_inventory_compiled(
            turn_id="turn-1",
            answer_version=1,
            semantic_event_id=fallback.event_id,
            admitted_candidates=[],
            excluded_candidates=[{"opportunity_id": "late-shadow-route", "reason": "semantic fallback", "evidence_event_ids": [fallback.event_id]}],
            idempotency_key="inventory:timeout",
        )
        evidence = trace.record_evidence_state_updated(
            turn_id="turn-1",
            answer_version=1,
            semantic_event_id=fallback.event_id,
            opportunity_inventory_event_id=inventory.event_id,
            evidence_state={"status": "not_decision_ready", "shadow_excluded": True},
            source_event_ids=[fallback.event_id, inventory.event_id],
            idempotency_key="evidence:timeout",
        )
        self.assertTrue(evidence.accepted)
        self.assertTrue(trace.verify_integrity())

    def test_rejected_route_cannot_materialize_or_become_spoken(self) -> None:
        trace = InterviewTraceV1("runner-rejected-route")
        session = trace.events[0]
        rejected = trace.record_state_transition_validated(
            turn_id="turn-1",
            answer_version=1,
            decision="rejected",
            visible_route_commit_allowed=True,
            source_opportunity_id="unsupported-route",
            source_evidence_event_ids=[session.event_id],
            reason="unsupported route",
            idempotency_key="validation:rejected-route",
        )
        self.assertFalse(rejected.accepted)
        with self.assertRaises(TraceInvariantError):
            trace.record_question_materialized(
                turn_id="turn-1",
                answer_version=1,
                question_id="must-not-serve",
                visible_text="This must not be visible.",
                source_opportunity_id="unsupported-route",
                source_evidence_event_ids=[session.event_id],
                idempotency_key="materialized:rejected-route",
            )
        self.assertFalse(any(event.event_type == TraceEventType.SPOKEN_QUESTION_COMMITTED.value for event in trace.events))
        self.assertTrue(trace.verify_integrity())

    def test_unsupported_report_evidence_is_rejected(self) -> None:
        trace, opening = self._opening("runner-report-evidence")
        started = trace.record_question_delivery_started(
            turn_id="turn-1", answer_version=1, question_prepared_event_id=opening["prepared"].event_id,
            delivery_attempt_id="delivery-turn-1-1", idempotency_key="delivery-start:report",
        )
        ack = trace.record_playback_acknowledged(
            turn_id="turn-1", answer_version=1, delivery_attempt_id="delivery-turn-1-1",
            delivery_started_event_id=started.event_id, idempotency_key="ack:report",
        )
        spoken = trace.record_spoken_question_committed(
            turn_id="turn-1", answer_version=1, question_id="question-turn-1", visible_text="Tell me about the work.",
            question_materialized_event_id=opening["materialized"].event_id, playback_ack_event_id=ack.event_id,
            delivery_attempt_id="delivery-turn-1-1", source_opportunity_id="opening-question",
            source_evidence_event_ids=[opening["session"].event_id], idempotency_key="spoken:report",
        )
        answer = trace.record_answer_received(
            turn_id="turn-1", answer_version=1, spoken_question_event_id=spoken.event_id,
            answer_text="I owned the analysis boundary.", idempotency_key="answer:report",
        )
        semantic = trace.record_semantic_interpretation_finalized(
            turn_id="turn-1", answer_version=1, answer_event_id=answer.event_id,
            interpretation={"status": "control"}, idempotency_key="semantic:report",
        )
        inventory = trace.record_opportunity_inventory_compiled(
            turn_id="turn-1", answer_version=1, semantic_event_id=semantic.event_id,
            admitted_candidates=[],
            excluded_candidates=[{"opportunity_id": "terminal", "reason": "terminal", "evidence_event_ids": [semantic.event_id]}],
            idempotency_key="inventory:report",
        )
        evidence = trace.record_evidence_state_updated(
            turn_id="turn-1", answer_version=1, semantic_event_id=semantic.event_id,
            opportunity_inventory_event_id=inventory.event_id, evidence_state={"status": "control"},
            source_event_ids=[semantic.event_id, inventory.event_id], idempotency_key="evidence:report",
        )
        with self.assertRaises(TraceReferenceError):
            trace.record_report_claim_emitted(
                claim_id="unsupported",
                claim_text="must not cite answer directly",
                source_evidence_event_ids=[answer.event_id],
                idempotency_key="claim:unsupported",
            )
        claim = trace.record_report_claim_emitted(
            claim_id="supported",
            claim_text="control evidence only",
            source_evidence_event_ids=[evidence.event_id],
            idempotency_key="claim:supported",
        )
        trace.record_final_evaluation_completed(
            evaluation_id="supported-final",
            report_claim_event_ids=[claim.event_id],
            evidence_event_ids=[evidence.event_id],
            evaluation_summary={"shadow_only": True},
            idempotency_key="final:supported",
        )
        self.assertTrue(trace.verify_integrity())

    async def test_session_store_and_telemetry_are_private(self) -> None:
        store = IsolatedSessionStore()
        telemetry = IsolatedTelemetrySink()
        await store.save_state("private", {"value": 1})
        state = await store.get_state("private")
        state["value"] = 2
        self.assertEqual((await store.get_state("private"))["value"], 1)
        await telemetry.log("private", "test", source="runner")
        self.assertEqual(len(telemetry.events), 1)
        self.assertEqual(store.session_ids, ("private",))


if __name__ == "__main__":
    unittest.main()
