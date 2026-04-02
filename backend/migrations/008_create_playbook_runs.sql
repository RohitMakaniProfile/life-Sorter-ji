-- Persist playbook generation outputs independent of session_store.

CREATE TABLE IF NOT EXISTS playbook_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    session_id      TEXT NOT NULL,
    user_id         UUID,

    status          TEXT NOT NULL DEFAULT 'running', -- running | complete | failed
    error           TEXT NOT NULL DEFAULT '',

    -- Inputs snapshot (optional but useful for debugging/replay)
    onboarding_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawl_snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Outputs
    context_brief   TEXT NOT NULL DEFAULT '',
    icp_card        TEXT NOT NULL DEFAULT '',
    playbook        TEXT NOT NULL DEFAULT '',
    website_audit   TEXT NOT NULL DEFAULT '',

    latencies       JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_session_id
    ON playbook_runs (session_id);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_user_id
    ON playbook_runs (user_id);

DROP TRIGGER IF EXISTS trg_playbook_runs_updated_at ON playbook_runs;
CREATE TRIGGER trg_playbook_runs_updated_at
    BEFORE UPDATE ON playbook_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

