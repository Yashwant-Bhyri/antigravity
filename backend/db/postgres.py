import logging
import os
import time
import json
import uuid
import asyncpg

_pool: asyncpg.Pool | None = None
_last_connect_error: str | None = None
_disabled_until = 0.0

_LOGGER = logging.getLogger(__name__)
_RETRY_COOLDOWN_SECS = 60


async def _mark_unavailable(exc: Exception):
    global _pool, _last_connect_error, _disabled_until
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None
    _disabled_until = time.time() + _RETRY_COOLDOWN_SECS
    message = f"{type(exc).__name__}: {exc}"
    if message != _last_connect_error:
        _LOGGER.warning(
            "Postgres unavailable; disabling DB-backed features for %ss. Reason: %s",
            _RETRY_COOLDOWN_SECS,
            message,
        )
        _last_connect_error = message


async def get_pool() -> asyncpg.Pool | None:
    global _pool, _last_connect_error
    if _pool is not None:
        return _pool

    if time.time() < _disabled_until:
        return None

    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                dsn=os.environ.get("DATABASE_URL", "postgresql://localhost/antigravity"),
                min_size=2,
                max_size=10,
            )
            if _last_connect_error is not None:
                _LOGGER.info("Postgres connection restored; DB-backed features re-enabled.")
                _last_connect_error = None
        except Exception as exc:
            await _mark_unavailable(exc)
            return None
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def init_schema():
    """Create tables if they don't exist. Called at app startup."""
    pool = await get_pool()
    if pool is None:
        return False
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id          TEXT PRIMARY KEY,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resume_snippet      TEXT,
                hire_recommendation TEXT,
                overall_score       NUMERIC(4,1),
                sprint_reached      INTEGER,
                duration_minutes    NUMERIC(5,1),
                full_report         JSONB
            )
        """)
        # Add full_report column to existing installs that predate this migration.
        await conn.execute("""
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS full_report JSONB
        """)
        await conn.execute("""
            ALTER TABLE sessions
              ADD COLUMN IF NOT EXISTS candidate_name TEXT,
              ADD COLUMN IF NOT EXISTS target_role TEXT,
              ADD COLUMN IF NOT EXISTS years_experience TEXT,
              ADD COLUMN IF NOT EXISTS report_schema_version TEXT,
              ADD COLUMN IF NOT EXISTS telemetry_summary JSONB,
              ADD COLUMN IF NOT EXISTS session_snapshot JSONB,
              ADD COLUMN IF NOT EXISTS report_ready_at TIMESTAMPTZ
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS interview_events (
                event_id       TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL,
                event_ts       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                event_name     TEXT NOT NULL,
                source         TEXT,
                level          TEXT,
                payload        JSONB NOT NULL,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS interview_events_session_ts_idx ON interview_events(session_id, event_ts)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS delivery_outbox (
                id              TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                destination     TEXT NOT NULL,
                event_type      TEXT NOT NULL,
                payload         JSONB NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                attempts        INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_error      TEXT,
                delivered_at    TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(session_id, destination, event_type)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS delivery_outbox_pending_idx ON delivery_outbox(status, next_attempt_at)")
    return True


async def persist_session(
    session_id: str,
    resume_snippet: str,
    hire_recommendation: str,
    overall_score: float,
    sprint_reached: int,
    duration_minutes: float,
    full_report: dict | None = None,
    candidate_name: str = "",
    target_role: str = "",
    years_experience: str = "",
    telemetry_summary: dict | None = None,
    session_snapshot: dict | None = None,
):
    """Write completed session to Postgres. Called once at end_session()."""
    pool = await get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sessions (
                    session_id, resume_snippet, hire_recommendation, overall_score,
                    sprint_reached, duration_minutes, full_report, candidate_name,
                    target_role, years_experience, report_schema_version,
                    telemetry_summary, session_snapshot, report_ready_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    hire_recommendation = EXCLUDED.hire_recommendation,
                    overall_score       = EXCLUDED.overall_score,
                    sprint_reached      = EXCLUDED.sprint_reached,
                    duration_minutes    = EXCLUDED.duration_minutes,
                    full_report         = EXCLUDED.full_report,
                    candidate_name      = EXCLUDED.candidate_name,
                    target_role         = EXCLUDED.target_role,
                    years_experience    = EXCLUDED.years_experience,
                    report_schema_version = EXCLUDED.report_schema_version,
                    telemetry_summary   = EXCLUDED.telemetry_summary,
                    session_snapshot    = EXCLUDED.session_snapshot,
                    report_ready_at     = EXCLUDED.report_ready_at
                """,
                session_id,
                resume_snippet[:200] if resume_snippet else "",
                hire_recommendation,
                overall_score,
                sprint_reached,
                duration_minutes,
                json.dumps(full_report) if full_report else None,
                candidate_name,
                target_role,
                years_experience,
                str((full_report or {}).get("schema_version") or "legacy_report"),
                json.dumps(telemetry_summary or {}),
                json.dumps(session_snapshot or {}),
            )
        return True
    except Exception as exc:
        await _mark_unavailable(exc)
        return False


async def append_interview_event(record: dict) -> bool:
    """Idempotently persist one telemetry fact without making the interview depend on Postgres."""
    pool = await get_pool()
    if pool is None:
        return False
    event_id = str(record.get("event_id") or uuid.uuid4())
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO interview_events(event_id, session_id, event_ts, event_name, source, level, payload)
                VALUES($1, $2, to_timestamp($3), $4, $5, $6, $7)
                ON CONFLICT(event_id) DO NOTHING
                """,
                event_id,
                str(record.get("session_id") or "unknown"),
                float(record.get("ts") or time.time()),
                str(record.get("event") or "unknown"),
                str(record.get("source") or "backend"),
                str(record.get("level") or "info"),
                json.dumps({**record, "event_id": event_id}),
            )
            # The final report callback contains the telemetry snapshot available
            # at finalization time. Events emitted after that snapshot (for
            # example callback-delivery confirmation or a late background-task
            # failure) must not remain stranded in Antigravity. Once a complete
            # handoff exists, queue every later fact as an idempotent delivery.
            handoff_id = await conn.fetchval(
                """
                SELECT payload->>'handoff_id'
                FROM delivery_outbox
                WHERE session_id=$1
                  AND destination='provenhire'
                  AND event_type='handoff_complete'
                LIMIT 1
                """,
                str(record.get("session_id") or "unknown"),
            )
            if handoff_id:
                delivery_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"provenhire-telemetry:{record.get('session_id')}:{event_id}",
                    )
                )
                event_type = f"handoff_telemetry:{event_id}"
                payload = {
                    "delivery_id": delivery_id,
                    "handoff_id": str(handoff_id),
                    "antigravity_session_id": str(record.get("session_id") or "unknown"),
                    "event": {**record, "event_id": event_id},
                }
                await conn.execute(
                    """
                    INSERT INTO delivery_outbox(id, session_id, destination, event_type, payload)
                    VALUES($1, $2, 'provenhire', $3, $4)
                    ON CONFLICT(session_id, destination, event_type) DO UPDATE SET
                        payload=EXCLUDED.payload,
                        status=CASE WHEN delivery_outbox.status='delivered' THEN 'delivered' ELSE 'pending' END,
                        updated_at=NOW()
                    """,
                    delivery_id,
                    str(record.get("session_id") or "unknown"),
                    event_type,
                    json.dumps(payload),
                )
        return True
    except Exception as exc:
        await _mark_unavailable(exc)
        return False


async def get_interview_events(session_id: str, limit: int = 0) -> list[dict]:
    pool = await get_pool()
    if pool is None:
        return []
    sql = "SELECT payload FROM interview_events WHERE session_id=$1 ORDER BY event_ts, created_at"
    args: list = [session_id]
    if limit > 0:
        sql += " LIMIT $2"
        args.append(limit)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(row["payload"]) if not isinstance(row["payload"], str) else json.loads(row["payload"]) for row in rows]
    except Exception as exc:
        await _mark_unavailable(exc)
        return []


async def enqueue_delivery(
    session_id: str,
    destination: str,
    event_type: str,
    payload: dict,
) -> str | None:
    pool = await get_pool()
    if pool is None:
        return None
    delivery_id = str(payload.get("delivery_id") or uuid.uuid4())
    payload = {**payload, "delivery_id": delivery_id}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO delivery_outbox(id, session_id, destination, event_type, payload)
                VALUES($1, $2, $3, $4, $5)
                ON CONFLICT(session_id, destination, event_type) DO UPDATE SET
                    payload=EXCLUDED.payload,
                    status=CASE WHEN delivery_outbox.status='delivered' THEN 'delivered' ELSE 'pending' END,
                    updated_at=NOW()
                RETURNING id
                """,
                delivery_id, session_id, destination, event_type, json.dumps(payload),
            )
        return str(row["id"])
    except Exception as exc:
        await _mark_unavailable(exc)
        return None


async def list_pending_deliveries(limit: int = 20) -> list[dict]:
    pool = await get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM delivery_outbox
                WHERE status IN ('pending', 'retry') AND next_attempt_at <= NOW()
                ORDER BY created_at
                LIMIT $1
                """,
                limit,
            )
        return [dict(row) for row in rows]
    except Exception as exc:
        await _mark_unavailable(exc)
        return []


async def mark_delivery_result(delivery_id: str, *, delivered: bool, error: str = "") -> None:
    pool = await get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            if delivered:
                await conn.execute(
                    """UPDATE delivery_outbox SET status='delivered', attempts=attempts+1,
                       delivered_at=NOW(), last_error=NULL, updated_at=NOW() WHERE id=$1""",
                    delivery_id,
                )
            else:
                await conn.execute(
                    """UPDATE delivery_outbox SET status='retry', attempts=attempts+1,
                       next_attempt_at=NOW() + (LEAST(900, 5 * POWER(2, LEAST(attempts, 8))) * INTERVAL '1 second'),
                       last_error=$2, updated_at=NOW() WHERE id=$1""",
                    delivery_id, error[:2000],
                )
    except Exception as exc:
        await _mark_unavailable(exc)


async def get_session_report(session_id: str) -> dict | None:
    """Retrieve persisted full report from Postgres — fallback when Redis has expired."""
    pool = await get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT full_report, hire_recommendation, overall_score, sprint_reached FROM sessions WHERE session_id = $1",
                session_id,
            )
        if not row:
            return None
        if row["full_report"]:
            raw_report = row["full_report"]
            if isinstance(raw_report, str):
                report = json.loads(raw_report)
            else:
                report = dict(raw_report)
            report["complete"] = True
            return report
        # Fallback: reconstruct minimal report from summary columns
        return {
            "complete": True,
            "hire_recommendation": row["hire_recommendation"],
            "overall_score": float(row["overall_score"]) if row["overall_score"] is not None else None,
            "sprint_reached": row["sprint_reached"],
        }
    except Exception as exc:
        await _mark_unavailable(exc)
        return None


async def list_sessions() -> list[dict]:
    """Returns all completed sessions for the recruiter dashboard."""
    pool = await get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            )
    except Exception as exc:
        await _mark_unavailable(exc)
        return []
    return [dict(r) for r in rows]
