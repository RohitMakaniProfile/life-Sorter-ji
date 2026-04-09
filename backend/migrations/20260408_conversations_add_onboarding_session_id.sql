ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS onboarding_session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_onboarding_session_id
    ON conversations (onboarding_session_id);
