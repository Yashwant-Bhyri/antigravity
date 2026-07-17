import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.orchestrator import Orchestrator


class FinalizationPipelineDrainContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orchestrator = Orchestrator.__new__(Orchestrator)
        self.orchestrator._pipeline_tasks = {}
        self.orchestrator._trace = AsyncMock()

    async def test_failed_report_persistence_remains_retryable(self):
        self.orchestrator.session_manager = type(
            "StateManager",
            (),
            {"save_state": AsyncMock()},
        )()
        state = {
            "session_id": "session-4",
            "final_evaluation": {"overall_score": 82, "hire_recommendation": "HIRE"},
            "parsed_resume": {"candidate_name": "Test Candidate"},
            "external_handoff": {"handoff_id": "handoff-4"},
            "interview_start_time": 1,
        }
        report = {"session_id": "session-4", "overall_score": 82}

        with patch("backend.services.orchestrator.persist_session", AsyncMock(return_value=False)):
            persisted = await self.orchestrator._persist_completed_report(state, report)

        self.assertFalse(persisted)
        self.assertEqual(state["durability_status"], "deferred")
        self.assertEqual(state["delivery_status"], "not_queued")
        self.assertEqual(state["durable_report_payload"], report)

    async def test_atomic_outbox_makes_failed_immediate_delivery_safe(self):
        self.orchestrator.session_manager = type(
            "StateManager",
            (),
            {"save_state": AsyncMock()},
        )()
        state = {
            "session_id": "session-5",
            "final_evaluation": {"overall_score": 82, "hire_recommendation": "HIRE"},
            "parsed_resume": {},
            "external_handoff": {"handoff_id": "handoff-5"},
            "interview_start_time": 1,
        }
        report = {"session_id": "session-5", "overall_score": 82}

        with (
            patch("backend.services.orchestrator.persist_session", AsyncMock(return_value=True)),
            patch("backend.services.orchestrator.notify_handoff_complete", AsyncMock(return_value=False)),
        ):
            persisted = await self.orchestrator._persist_completed_report(state, report)

        self.assertTrue(persisted)
        self.assertEqual(state["durability_status"], "complete")
        self.assertEqual(state["delivery_status"], "queued_for_retry")
        self.assertNotIn("durable_report_payload", state)

    async def test_drain_waits_for_pipeline_and_child_score(self):
        completed: list[str] = []

        async def score():
            await asyncio.sleep(0.01)
            completed.append("score")

        async def pipeline():
            await asyncio.sleep(0.01)
            self.orchestrator._track_pipeline_task(
                "session-1",
                score(),
                name="score",
            )
            completed.append("pipeline")

        self.orchestrator._track_pipeline_task(
            "session-1",
            pipeline(),
            name="pipeline",
        )
        result = await self.orchestrator._drain_pipeline_tasks("session-1")

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["evidence_complete"])
        self.assertEqual(result["pending_task_count"], 0)
        self.assertEqual(completed, ["pipeline", "score"])

    async def test_timeout_is_explicit_and_does_not_cancel_analysis(self):
        release = asyncio.Event()

        async def pipeline():
            await release.wait()

        task = self.orchestrator._track_pipeline_task(
            "session-2",
            pipeline(),
            name="slow-pipeline",
        )
        with patch.dict(os.environ, {"FINALIZATION_PIPELINE_DRAIN_TIMEOUT_SECONDS": "0.01"}):
            result = await self.orchestrator._drain_pipeline_tasks("session-2")

        self.assertEqual(result["status"], "timed_out")
        self.assertFalse(result["evidence_complete"])
        self.assertEqual(result["pending_task_count"], 1)
        self.assertFalse(task.cancelled())
        release.set()
        await task

    async def test_failed_task_result_is_consumed_and_registry_is_cleaned(self):
        async def pipeline():
            raise RuntimeError("expected contract failure")

        task = self.orchestrator._track_pipeline_task(
            "session-3",
            pipeline(),
            name="failed-pipeline",
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertTrue(task.done())
        self.assertIsInstance(task.exception(), RuntimeError)
        self.assertNotIn("session-3", self.orchestrator._pipeline_tasks)


if __name__ == "__main__":
    unittest.main()
