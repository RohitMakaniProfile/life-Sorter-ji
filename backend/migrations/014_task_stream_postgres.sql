-- Task stream persistence (alternative to Redis Streams) for SSE resume / multi-instance.
-- Enable with TASKSTREAM_BACKEND=postgres

CREATE TABLE IF NOT EXISTS task_stream_streams (
    stream_id       TEXT PRIMARY KEY,
    task_type       TEXT NOT NULL,
    session_id      TEXT NOT NULL DEFAULT '',
    user_id         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'running',
    last_seq        INTEGER NOT NULL DEFAULT 0,
    last_event_id   BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_stream_streams_expires_at
    ON task_stream_streams (expires_at);

CREATE TABLE IF NOT EXISTS task_stream_events (
    id              BIGSERIAL PRIMARY KEY,
    stream_id       TEXT NOT NULL REFERENCES task_stream_streams(stream_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    event           JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_stream_events_stream_id_id
    ON task_stream_events (stream_id, id);

CREATE TABLE IF NOT EXISTS task_stream_maps (
    id              BIGSERIAL PRIMARY KEY,
    task_type       TEXT NOT NULL,
    map_kind        TEXT NOT NULL CHECK (map_kind IN ('session', 'user')),
    map_key         TEXT NOT NULL,
    stream_id       TEXT NOT NULL REFERENCES task_stream_streams(stream_id) ON DELETE CASCADE,
    expires_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (task_type, map_kind, map_key)
);

CREATE INDEX IF NOT EXISTS idx_task_stream_maps_expires_at
    ON task_stream_maps (expires_at);

CREATE TABLE IF NOT EXISTS task_stream_spawn_locks (
    lock_key        TEXT PRIMARY KEY,
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_stream_spawn_locks_expires_at
    ON task_stream_spawn_locks (expires_at);
