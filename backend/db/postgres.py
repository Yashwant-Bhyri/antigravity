import os
import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=os.environ.get("DATABASE_URL", "postgresql://localhost/antigravity"),
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def init_schema():
    """Create tables if they don't exist. Called at app startup."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id          TEXT PRIMARY KEY,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resume_snippet      TEXT,
                hire_recommendation TEXT,
                overall_score       NUMERIC(4,1),
                sprint_reached      INTEGER,
                duration_minutes    NUMERIC(5,1)
            )
        """)


async def persist_session(
    session_id: str,
    resume_snippet: str,
    hire_recommendation: str,
    overall_score: float,
    sprint_reached: int,
    duration_minutes: float,
):
    """Write completed session to Postgres. Called once at end_session()."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (session_id, resume_snippet, hire_recommendation, overall_score, sprint_reached, duration_minutes)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (session_id) DO UPDATE SET
                hire_recommendation = EXCLUDED.hire_recommendation,
                overall_score       = EXCLUDED.overall_score,
                sprint_reached      = EXCLUDED.sprint_reached,
                duration_minutes    = EXCLUDED.duration_minutes
            """,
            session_id,
            resume_snippet[:200] if resume_snippet else "",
            hire_recommendation,
            overall_score,
            sprint_reached,
            duration_minutes,
        )


async def list_sessions() -> list[dict]:
    """Returns all completed sessions for the recruiter dashboard."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        )
    return [dict(r) for r in rows]
