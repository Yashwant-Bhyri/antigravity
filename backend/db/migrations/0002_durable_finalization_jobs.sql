CREATE TABLE IF NOT EXISTS finalization_jobs (
    session_id          TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    state_snapshot      JSONB NOT NULL,
    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 8,
    next_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at           TIMESTAMPTZ,
    locked_by           TEXT,
    last_error          TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS finalization_jobs_recovery_idx
    ON finalization_jobs(status, next_attempt_at, updated_at);

CREATE TABLE IF NOT EXISTS session_checkpoints (
    session_id          TEXT PRIMARY KEY,
    lifecycle_status    TEXT NOT NULL,
    state_snapshot      JSONB NOT NULL,
    checkpoint_reason   TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_checkpoints_status_idx
    ON session_checkpoints(lifecycle_status, updated_at);
