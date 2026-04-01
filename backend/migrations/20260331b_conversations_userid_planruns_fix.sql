-- ═══════════════════════════════════════════════════════════════════════════════
-- MIGRATION 20260331b — Fix remaining prod gaps
-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. conversations.user_id TEXT column + index (was missing, causes runtime error)
-- 2. plan_runs status check: add 'executing' and 'cancelled' values
-- 3. agent_config_versions.created_by_session_id TEXT (canonical name; keep
--    existing created_by_user_id intact so no data is lost)
-- ═══════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. conversations.user_id
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS user_id TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_user_id
    ON conversations (user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. plan_runs status check — add 'executing' and 'cancelled'
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE plan_runs
    DROP CONSTRAINT IF EXISTS plan_runs_status_check;

ALTER TABLE plan_runs
    ADD CONSTRAINT plan_runs_status_check
    CHECK (status IN ('draft', 'approved', 'running', 'executing', 'done', 'error', 'cancelled'));

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. agent_config_versions.created_by_session_id
--    Canonical uses this TEXT column; prod only has created_by_user_id (uuid FK).
--    Add the TEXT column so app code writing session_id doesn't break.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE agent_config_versions
    ADD COLUMN IF NOT EXISTS created_by_session_id TEXT;