-- Add onboarding_session_id to conversations table
-- Links a chat conversation back to the onboarding session that started it

ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS onboarding_session_id TEXT REFERENCES onboarding(session_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_conversations_onboarding_session_id
    ON conversations (onboarding_session_id)
    WHERE onboarding_session_id IS NOT NULL;
