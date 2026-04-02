-- Enforce "1 row per session" for onboarding.
-- This matches the intended canonical model: session_id uniquely identifies an onboarding journey state row.
-- Idempotent: safe to re-run (PostgreSQL <15 has no ADD CONSTRAINT IF NOT EXISTS).

-- If old data has multiple rows per session_id, you must dedupe before this can succeed.
-- (Keep the latest row and delete older ones.)

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'onboarding_session_id_unique'
      AND conrelid = 'public.onboarding'::regclass
  ) THEN
    ALTER TABLE onboarding
      ADD CONSTRAINT onboarding_session_id_unique UNIQUE (session_id);
  END IF;
END $$;
