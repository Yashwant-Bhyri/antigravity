import inspect
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.interview_telemetry import InterviewTelemetry
from backend.services.orchestrator import Orchestrator


class DurableReportPipelineContract(unittest.IsolatedAsyncioTestCase):
    async def test_telemetry_has_stable_id_and_dual_writes(self):
        telemetry = InterviewTelemetry()
        local_append = AsyncMock()
        postgres_append = AsyncMock(return_value=True)

        with (
            patch("asyncio.to_thread", local_append),
            patch("backend.db.postgres.append_interview_event", postgres_append),
        ):
            record = await telemetry.log(
                "contract-session",
                "contract.event",
                source="contract",
                fact="retained",
            )

        self.assertTrue(record["event_id"])
        self.assertEqual(record["session_id"], "contract-session")
        self.assertEqual(record["fact"], "retained")
        local_append.assert_awaited_once()
        postgres_append.assert_awaited_once_with(record)

    def test_finalization_awaits_report_persistence(self):
        source = inspect.getsource(Orchestrator.end_session)
        persistence_source = inspect.getsource(Orchestrator._persist_completed_report)
        self.assertIn("await self._persist_completed_report(state, full_report)", source)
        self.assertIn("persisted = await persist_session(", persistence_source)
        self.assertNotIn("create_task(persist_session(", source)
        self.assertIn('"final_evidence_packet"', source)
        self.assertIn('"telemetry_events"', source)
        self.assertIn("delivered = await notify_handoff_complete(", persistence_source)


if __name__ == "__main__":
    unittest.main()
