import json
import os
import asyncio
import redis.asyncio as redis


class SessionManager:
    """
    Manages interview session state in Redis.
    All agents read/write through here — never pass raw transcripts between agents.
    """

    def __init__(self):
        # Support Upstash/Vercel standard prefixes without crashing
        self.redis_url = os.environ.get("KV_URL") or os.environ.get("REDIS_URL") or os.environ.get("STORAGE_URL", "redis://localhost:6379")
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        self.ttl = 14400         # 4 hours for live sessions
        self.completed_ttl = 86400  # 24 hours after completion so Provenhire can always poll

    def _new_client(self):
        return redis.from_url(self.redis_url, decode_responses=True)

    async def _reset_client(self):
        try:
            await self.redis.aclose()
        except Exception:
            pass
        self.redis = self._new_client()

    async def _redis_call(self, operation):
        last_error = None
        for attempt in range(2):
            try:
                return await operation()
            except (redis.ConnectionError, redis.TimeoutError) as exc:
                last_error = exc
                await self._reset_client()
                if attempt == 0:
                    await asyncio.sleep(0.05)
        if last_error:
            raise last_error
        return None

    async def save_state(self, session_id: str, state: dict):
        ttl = self.completed_ttl if state.get("interview_complete") else self.ttl
        payload = json.dumps(state)
        await self._redis_call(lambda: self.redis.setex(session_id, ttl, payload))

    async def get_state(self, session_id: str) -> dict:
        data = await self._redis_call(lambda: self.redis.get(session_id))
        if not data:
            raise KeyError(f"Session not found: {session_id}")
        return json.loads(data)

    async def delete_session(self, session_id: str):
        await self._redis_call(lambda: self.redis.delete(session_id))
