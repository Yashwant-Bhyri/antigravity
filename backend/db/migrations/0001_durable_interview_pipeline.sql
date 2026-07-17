CREATE TABLE IF NOT EXISTS sessions (
    session_id          TEXT PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resume_snippet      TEXT,
    hire_recommendation TEXT,
    overall_score       NUMERIC(4,1),
    sprint_reached      INTEGER,
    duration_minutes    NUMERIC(5,1),
    full_report         JSONB
);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS full_report JSONB,
    ADD COLUMN IF NOT EXISTS candidate_name TEXT,
    ADD COLUMN IF NOT EXISTS target_role TEXT,
    ADD COLUMN IF NOT EXISTS years_experience TEXT,
    ADD COLUMN IF NOT EXISTS report_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS telemetry_summary JSONB,
    ADD COLUMN IF NOT EXISTS session_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS report_ready_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS interview_events (
    event_id       TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    event_ts       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_name     TEXT NOT NULL,
    source         TEXT,
    level          TEXT,
    payload        JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS interview_events_session_ts_idx
    ON interview_events(session_id, event_ts);

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
);

CREATE INDEX IF NOT EXISTS delivery_outbox_pending_idx
    ON delivery_outbox(status, next_attempt_at);
