"""One-world, one-run deterministic CompleteInterviewRunnerV1 checkpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import stat
import tempfile
import unittest
from pathlib import Path

try:
    from backend.services.complete_interview_runner_v1 import (
        CompleteInterviewRunnerConfig,
        CompleteInterviewRunnerV1,
        DEFAULT_WORLD_ID,
        sha256_json,
    )
    from backend.services.interview_trace_v1 import InterviewTraceV1, TraceEventType, TraceView
except ModuleNotFoundError:  # direct execution from the backend directory
    from services.complete_interview_runner_v1 import (
        CompleteInterviewRunnerConfig,
        CompleteInterviewRunnerV1,
        DEFAULT_WORLD_ID,
        sha256_json,
    )
    from services.interview_trace_v1 import InterviewTraceV1, TraceEventType, TraceView


class CompleteInterviewRunnerV1ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_world_01_control_reaches_fifteen_real_production_turns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="complete-runner-v1-control-") as directory:
            result = await CompleteInterviewRunnerV1(
                CompleteInterviewRunnerConfig(
                    world_id=DEFAULT_WORLD_ID,
                    max_turns=15,
                    artifact_dir=Path(directory),
                    quiescence_timeout_seconds=8.0,
                )
            ).run()
            artifact_path = Path(result.artifact_path)
            manifest_path = Path(result.manifest_path)
            self.assertTrue(artifact_path.exists())
            self.assertTrue(manifest_path.exists())
            artifact_bytes = artifact_path.read_bytes()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["redacted_artifact_sha256"], hashlib.sha256(artifact_bytes).hexdigest())
            self.assertEqual(manifest["redacted_artifact_file"], artifact_path.name)
            canonical_trace_path = Path(directory) / manifest["canonical_trace_file"]
            self.assertTrue(canonical_trace_path.exists())
            self.assertEqual(stat.S_IMODE(canonical_trace_path.stat().st_mode), 0o600)
            canonical_trace_bytes = canonical_trace_path.read_bytes()
            self.assertEqual(
                manifest["canonical_trace_sha256"],
                hashlib.sha256(canonical_trace_bytes).hexdigest(),
            )
            canonical_records = json.loads(canonical_trace_bytes.decode("utf-8"))
            canonical_trace = InterviewTraceV1.from_records(canonical_records)
            self.assertTrue(canonical_trace.verify_integrity())
            self.assertEqual(
                canonical_trace.canonical_spoken_history(),
                result.canonical_spoken_history,
            )
            self.assertEqual(
                manifest["canonical_spoken_history_sha256"],
                sha256_json(result.canonical_spoken_history),
            )
            artifact = json.loads(artifact_bytes.decode("utf-8"))
            self.assertEqual(artifact["artifact_kind"], "redacted_projection_only")
            self.assertTrue(artifact["trace"]["source_trace_integrity_verified_before_redaction"])
            self.assertNotIn("integrity_verified", artifact["trace"])
            def all_keys(value: object) -> set[str]:
                if isinstance(value, dict):
                    return set(value) | {key for child in value.values() for key in all_keys(child)}
                if isinstance(value, list):
                    return {key for child in value for key in all_keys(child)}
                return set()

            self.assertNotIn("integrity_verified", all_keys(artifact))
            unsafe_secret_value = re.compile(
                r"(?:api[_-]?key\s*[:=]|password\s*[:=]|secret\s*[:=]|"
                r"credential\s*[:=]|bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
                r"(?:sk|rk|ghp|github_pat|xox[baprs]-|AIza|AKIA)[A-Za-z0-9_-]{8,})",
                re.IGNORECASE,
            )
            self.assertIsNone(unsafe_secret_value.search(canonical_trace_bytes.decode("utf-8")))

        self.assertEqual(result.status, "complete", result.blocker)
        self.assertEqual(result.turns_committed, 15)
        self.assertEqual(len(result.canonical_spoken_history), 15)
        self.assertIsNone(result.blocker)
        self.assertTrue(result.trace_records)
        self.assertTrue(InterviewTraceV1.from_records(result.trace_records).verify_integrity())

        event_types = {item["event_type"] for item in result.trace_records}
        required = {
            TraceEventType.SESSION_STARTED.value,
            TraceEventType.QUESTION_MATERIALIZED.value,
            TraceEventType.QUESTION_PREPARED.value,
            TraceEventType.QUESTION_DELIVERY_STARTED.value,
            TraceEventType.PLAYBACK_ACKNOWLEDGED.value,
            TraceEventType.SPOKEN_QUESTION_COMMITTED.value,
            TraceEventType.ANSWER_RECEIVED.value,
            TraceEventType.SEMANTIC_INTERPRETATION_FINALIZED.value,
            TraceEventType.OPPORTUNITY_INVENTORY_COMPILED.value,
            TraceEventType.ACTION_GRANT_SELECTED.value,
            TraceEventType.EVIDENCE_STATE_UPDATED.value,
            TraceEventType.REPORT_CLAIM_EMITTED.value,
            TraceEventType.FINAL_EVALUATION_COMPLETED.value,
        }
        self.assertTrue(required.issubset(event_types), sorted(required - event_types))

        materialized = {
            item["turn_id"]: item["payload"]["views"][TraceView.EVALUATOR.value]
            for item in result.trace_records
            if item["event_type"] == TraceEventType.QUESTION_MATERIALIZED.value
        }
        answers = {
            item["turn_id"]: item["payload"]["views"][TraceView.EVALUATOR.value]
            for item in result.trace_records
            if item["event_type"] == TraceEventType.ANSWER_RECEIVED.value
        }
        self.assertEqual(set(materialized), set(answers))
        for turn in result.canonical_spoken_history:
            self.assertEqual(
                turn["question_text"],
                materialized[turn["turn_id"]]["question_text"],
            )
            self.assertEqual(
                turn["answer_text"],
                answers[turn["turn_id"]]["answer_text"],
            )
        self.assertNotIn("fact_", json.dumps(result.trace_records, ensure_ascii=True))

        for quiescence in result.quiescence:
            self.assertFalse(quiescence["timed_out"], quiescence)
            self.assertEqual(quiescence["pipeline_inflight"], 0, quiescence)
            self.assertEqual(quiescence["turn_pipeline_running"], 0, quiescence)
            self.assertFalse(quiescence["hydration_inflight"], quiescence)
        self.assertTrue(result.report_summary["shadow_only"])
        self.assertEqual(result.report_summary["candidate_quality_claim"], "not_assessed")
        self.assertIn("deterministic actual-grant fixture/control only", result.adapter_audit["candidate_actor_quality"])
        self.assertIn("paid LLM providers", result.adapter_audit["forbidden_external_state_touched"])


if __name__ == "__main__":
    unittest.main()
