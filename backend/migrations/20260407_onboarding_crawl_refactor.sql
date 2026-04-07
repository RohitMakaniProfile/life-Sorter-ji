-- ─────────────────────────────────────────────────────────────────────────────
-- Onboarding crawl refactor
-- 1. Add web_summary to onboarding table
-- 2. Extend skill_calls to support onboarding context (no conversations FK)
--    - make conversation_id nullable
--    - add onboarding_session_id column
--    - enforce exactly one context is set
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. web_summary on onboarding
ALTER TABLE onboarding
    ADD COLUMN IF NOT EXISTS web_summary TEXT NOT NULL DEFAULT '';

-- 2a. Make conversation_id and message_id nullable (were NOT NULL)
ALTER TABLE skill_calls
    ALTER COLUMN conversation_id DROP NOT NULL;

ALTER TABLE skill_calls
    ALTER COLUMN message_id DROP NOT NULL;

-- 2b. Add onboarding_session_id
ALTER TABLE skill_calls
    ADD COLUMN IF NOT EXISTS onboarding_session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_skill_calls_onboarding_session_id
    ON skill_calls (onboarding_session_id)
    WHERE onboarding_session_id IS NOT NULL;

-- 2c. Exactly one context must be set
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'skill_calls_context_check'
          AND conrelid = 'public.skill_calls'::regclass
    ) THEN
        ALTER TABLE skill_calls
            ADD CONSTRAINT skill_calls_context_check CHECK (
                (conversation_id IS NOT NULL AND onboarding_session_id IS NULL) OR
                (conversation_id IS NULL     AND onboarding_session_id IS NOT NULL)
            );
    END IF;
END $$;