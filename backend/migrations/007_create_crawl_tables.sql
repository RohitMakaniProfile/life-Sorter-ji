-- Crawl persistence for reuse across sessions (cache) + per-request audit (runs).

CREATE TABLE IF NOT EXISTS crawl_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    normalized_url  TEXT NOT NULL,
    crawler_version TEXT NOT NULL DEFAULT 'v1',

    crawl_raw       JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawl_summary   JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_crawl_cache_url_version
    ON crawl_cache (normalized_url, crawler_version);

DROP TRIGGER IF EXISTS trg_crawl_cache_updated_at ON crawl_cache;
CREATE TRIGGER trg_crawl_cache_updated_at
    BEFORE UPDATE ON crawl_cache
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


CREATE TABLE IF NOT EXISTS crawl_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    session_id      TEXT NOT NULL,
    user_id         UUID,

    input_url       TEXT NOT NULL,
    normalized_url  TEXT NOT NULL,
    url_type        TEXT NOT NULL DEFAULT 'website', -- website | gbp | social_profile

    status          TEXT NOT NULL DEFAULT 'running', -- running | complete | failed
    cache_hit       BOOLEAN NOT NULL DEFAULT FALSE,

    crawl_cache_id  UUID REFERENCES crawl_cache(id) ON DELETE SET NULL,

    error           TEXT NOT NULL DEFAULT '',

    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_session_id
    ON crawl_runs (session_id);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_user_id
    ON crawl_runs (user_id);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_normalized_url
    ON crawl_runs (normalized_url);

DROP TRIGGER IF EXISTS trg_crawl_runs_updated_at ON crawl_runs;
CREATE TRIGGER trg_crawl_runs_updated_at
    BEFORE UPDATE ON crawl_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

