-- Add conversation_id to onboarding table
-- Links the onboarding journey to its associated conversation for Phase 2 access

ALTER TABLE onboarding
    ADD COLUMN IF NOT EXISTS conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_onboarding_conversation_id
    ON onboarding (conversation_id)
    WHERE conversation_id IS NOT NULL;

COMMENT ON COLUMN onboarding.conversation_id IS
    'Links this onboarding row to its Phase 2 conversation for playbook access and chat history.';

