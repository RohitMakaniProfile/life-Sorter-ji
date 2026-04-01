-- Add `onboarding` table (Phase 1 journey snapshot). Idempotent; safe to re-run.
-- Requires existing `user_sessions(session_id)` for the foreign key.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS onboarding (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    session_id      TEXT NOT NULL REFERENCES user_sessions (session_id) ON DELETE CASCADE,
    user_id         TEXT,

    outcome         TEXT,
    domain          TEXT,
    task            TEXT,

    website_url     TEXT,
    gbp_url         TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_session_id
    ON onboarding (session_id);

CREATE INDEX IF NOT EXISTS idx_onboarding_user_id
    ON onboarding (user_id)
    WHERE user_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_onboarding_updated_at ON onboarding;
CREATE TRIGGER trg_onboarding_updated_at
    BEFORE UPDATE ON onboarding
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE onboarding IS
    'Onboarding flow selections and URLs per session; user_id nullable until identity is linked.';
