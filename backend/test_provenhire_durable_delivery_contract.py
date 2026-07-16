import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.provenhire_handoff import (
    notify_handoff_complete,
    notify_handoff_started,
    process_pending_handoff_deliveries,
)


class _Response:
    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, post: AsyncMock, *args, **kwargs):
        self._post = post

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return await self._post(*args, **kwargs)


class ProvenHireDurableDeliveryContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["PROVENHIRE_API_URL"] = "https://provenhire.example"
        os.environ["ANTIGRAVITY_WEBHOOK_SECRET"] = "contract-secret"

    async def test_complete_is_enqueued_before_immediate_delivery(self):
        post = AsyncMock(return_value=_Response())
        enqueue = AsyncMock(return_value="delivery-1")
        mark = AsyncMock()
        with (
            patch("backend.db.postgres.enqueue_delivery", enqueue),
            patch("backend.db.postgres.mark_delivery_result", mark),
            patch(
                "backend.services.provenhire_handoff.httpx.AsyncClient",
                side_effect=lambda *args, **kwargs: _Client(post, *args, **kwargs),
            ),
        ):
            delivered = await notify_handoff_complete(
                "handoff-1",
                "session-1",
                {"complete": True, "schema_version": "final_report_v2"},
            )

        self.assertTrue(delivered)
        enqueue.assert_awaited_once()
        body = post.await_args.kwargs["json"]
        self.assertEqual(body["delivery_id"], "delivery-1")
        mark.assert_awaited_once_with("delivery-1", delivered=True)

    async def test_started_returns_after_durable_enqueue_without_network_wait(self):
        enqueue = AsyncMock(return_value="delivery-started")
        with (
            patch("backend.db.postgres.enqueue_delivery", enqueue),
            patch("backend.db.postgres.mark_delivery_result", AsyncMock()),
            patch("backend.services.provenhire_handoff.httpx.AsyncClient") as client,
        ):
            queued = await notify_handoff_started("handoff-2", "session-2")

        self.assertTrue(queued)
        enqueue.assert_awaited_once()
        client.assert_not_called()

    async def test_late_telemetry_outbox_row_uses_signed_telemetry_endpoint(self):
        post = AsyncMock(return_value=_Response())
        mark = AsyncMock()
        pending = AsyncMock(
            return_value=[
                {
                    "id": "delivery-telemetry-1",
                    "destination": "provenhire",
                    "event_type": "handoff_telemetry:event-1",
                    "payload": {
                        "handoff_id": "handoff-1",
                        "antigravity_session_id": "session-1",
                        "event": {"event_id": "event-1", "event": "late_failure"},
                    },
                }
            ]
        )
        with (
            patch("backend.db.postgres.list_pending_deliveries", pending),
            patch("backend.db.postgres.mark_delivery_result", mark),
            patch(
                "backend.services.provenhire_handoff.httpx.AsyncClient",
                side_effect=lambda *args, **kwargs: _Client(post, *args, **kwargs),
            ),
        ):
            delivered = await process_pending_handoff_deliveries()

        self.assertEqual(delivered, 1)
        self.assertTrue(post.await_args.args[0].endswith("/handoff-telemetry"))
        self.assertEqual(post.await_args.kwargs["json"]["delivery_id"], "delivery-telemetry-1")
        self.assertTrue(post.await_args.kwargs["headers"]["X-Antigravity-Signature"])
        mark.assert_awaited_once_with("delivery-telemetry-1", delivered=True)


if __name__ == "__main__":
    unittest.main()
