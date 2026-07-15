import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.provenhire_handoff import notify_handoff_complete, notify_handoff_started


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


if __name__ == "__main__":
    unittest.main()
