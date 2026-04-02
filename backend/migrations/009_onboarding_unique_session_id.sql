-- Enforce "1 row per session" for onboarding.
-- This matches the intended canonical model: session_id uniquely identifies an onboarding journey state row.
-- Idempotent: safe to re-run.

-- If old data has multiple rows per session_id, you must dedupe before this can succeed.
-- (Keep the latest row and delete older ones.)

ALTER TABLE onboarding
    ADD CONSTRAINT IF NOT EXISTS onboarding_session_id_unique UNIQUE (session_id);

