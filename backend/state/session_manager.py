import json
import os
import redis.asyncio as redis


class SessionManager:
    """
    Manages interview session state in Redis.
    All agents read/write through here — never pass raw transcripts between agents.
    """

    def __init__(self):
        self.redis = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        self.ttl = 3600  # 1 hour session expiry

    async def save_state(self, session_id: str, state: dict):
        await self.redis.setex(session_id, self.ttl, json.dumps(state))

    async def get_state(self, session_id: str) -> dict:
        data = await self.redis.get(session_id)
        if not data:
            raise KeyError(f"Session not found: {session_id}")
        return json.loads(data)

    async def delete_session(self, session_id: str):
        await self.redis.delete(session_id)
