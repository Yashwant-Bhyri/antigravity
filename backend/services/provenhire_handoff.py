import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)
_WEBHOOK_RETRY_DELAYS_SECONDS = [0, 5, 15]


def _api_base_url() -> str:
    raw = (os.getenv("PROVENHIRE_API_URL") or "").strip().rstrip("/")
    if not raw:
        return ""
    return raw if raw.endswith("/api") else f"{raw}/api"


def sign_handoff_event(event: str, handoff_id: str, session_id: str) -> str:
    secret = os.getenv("ANTIGRAVITY_WEBHOOK_SECRET") or os.getenv("PROVENHIRE_WEBHOOK_SECRET") or ""
    if not secret:
        raise RuntimeError("ANTIGRAVITY_WEBHOOK_SECRET is required for ProvenHire handoff callbacks")
    return hmac.new(
        secret.encode("utf-8"),
        f"{event}|{handoff_id}|{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def consume_launch_token(token: str) -> dict[str, Any]:
    base_url = _api_base_url()
    if not base_url:
        raise RuntimeError("PROVENHIRE_API_URL is required for handoff launch mode")

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)) as client:
        response = await client.post(
            f"{base_url}/ai-interview-adapter/handoff-consume",
            json={"token": token},
        )
    response.raise_for_status()
    return response.json()


async def notify_handoff_started(handoff_id: str, session_id: str) -> bool:
    return await _post_handoff_event(
        "started",
        {
            "handoff_id": handoff_id,
            "antigravity_session_id": session_id,
        },
        session_id=session_id,
        immediate=False,
    )


async def notify_handoff_complete(handoff_id: str, session_id: str, report: dict[str, Any]) -> bool:
    return await _post_handoff_event(
        "complete",
        {
            "handoff_id": handoff_id,
            "antigravity_session_id": session_id,
            "report": report,
        },
        session_id=session_id,
    )


async def notify_handoff_failed(handoff_id: str, session_id: str, error: str) -> bool:
    payload_session_id = "" if session_id == "none" else session_id
    return await _post_handoff_event(
        "failed",
        {
            "handoff_id": handoff_id,
            "antigravity_session_id": payload_session_id,
            "error": error,
        },
        session_id=session_id or "none",
    )


async def _post_handoff_event(
    event: str,
    payload: dict[str, Any],
    *,
    session_id: str,
    immediate: bool = True,
) -> bool:
    base_url = _api_base_url()
    if not base_url:
        return False
    from backend.db.postgres import enqueue_delivery, mark_delivery_result

    delivery_id = await enqueue_delivery(
        session_id,
        "provenhire",
        f"handoff_{event}",
        payload,
    )
    if delivery_id:
        payload = {**payload, "delivery_id": delivery_id}
        if not immediate:
            return True
    handoff_id = str(payload.get("handoff_id") or "")
    signature = sign_handoff_event(event, handoff_id, session_id)
    last_error: Exception | None = None
    for attempt, delay in enumerate(_WEBHOOK_RETRY_DELAYS_SECONDS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=10.0)) as client:
                response = await client.post(
                    f"{base_url}/ai-interview-adapter/handoff-{event}",
                    json=payload,
                    headers={"X-Antigravity-Signature": signature},
                )
            response.raise_for_status()
            if delivery_id:
                await mark_delivery_result(delivery_id, delivered=True)
            return True
        except Exception as exc:
            last_error = exc
            _LOGGER.warning(
                "ProvenHire handoff webhook failed: event=%s handoff=%s attempt=%s/%s error=%s",
                event,
                handoff_id,
                attempt,
                len(_WEBHOOK_RETRY_DELAYS_SECONDS),
                exc,
            )

    _LOGGER.error(
        "ProvenHire handoff webhook exhausted retries: event=%s handoff=%s session=%s error=%s",
        event,
        handoff_id,
        session_id,
        last_error,
    )
    if delivery_id:
        await mark_delivery_result(delivery_id, delivered=False, error=str(last_error or "delivery failed"))
    return False


async def process_pending_handoff_deliveries(limit: int = 20) -> int:
    """Retry durable ProvenHire callbacks. Safe to run from every backend instance."""
    from backend.db.postgres import list_pending_deliveries, mark_delivery_result

    base_url = _api_base_url()
    if not base_url:
        return 0
    delivered = 0
    for row in await list_pending_deliveries(limit=limit):
        if row.get("destination") != "provenhire":
            continue
        event_type = str(row.get("event_type") or "")
        if not event_type.startswith("handoff_"):
            continue
        event = (
            "telemetry"
            if event_type.startswith("handoff_telemetry:")
            else event_type.removeprefix("handoff_")
        )
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        payload = {**payload, "delivery_id": str(row.get("id"))}
        session_id = str(payload.get("antigravity_session_id") or "none") or "none"
        handoff_id = str(payload.get("handoff_id") or "")
        try:
            signature = sign_handoff_event(event, handoff_id, session_id)
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=30.0, write=20.0, pool=10.0)) as client:
                response = await client.post(
                    f"{base_url}/ai-interview-adapter/handoff-{event}",
                    json=payload,
                    headers={"X-Antigravity-Signature": signature},
                )
            response.raise_for_status()
            await mark_delivery_result(str(row.get("id")), delivered=True)
            delivered += 1
        except Exception as exc:
            await mark_delivery_result(str(row.get("id")), delivered=False, error=str(exc))
    return delivered
