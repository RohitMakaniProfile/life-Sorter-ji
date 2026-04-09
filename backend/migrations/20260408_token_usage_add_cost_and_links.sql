ALTER TABLE token_usage
    ADD COLUMN IF NOT EXISTS conversation_id TEXT,
    ADD COLUMN IF NOT EXISTS user_id TEXT,
    ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS model_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS cost_inr NUMERIC(12,2);

UPDATE token_usage
SET
    stage = COALESCE(NULLIF(split_part(model, '||', 1), ''), stage),
    provider = COALESCE(NULLIF(split_part(model, '||', 2), ''), provider),
    model_name = COALESCE(NULLIF(split_part(model, '||', 3), ''), model_name);

UPDATE token_usage tu
SET conversation_id = m.conversation_id
FROM messages m
WHERE (m.message->>'messageId') = tu.message_id
  AND tu.conversation_id IS NULL;

UPDATE token_usage tu
SET user_id = c.user_id
FROM conversations c
WHERE c.id = tu.conversation_id
  AND tu.user_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_token_usage_user_id_created_at
    ON token_usage (user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_token_usage_conversation_id_created_at
    ON token_usage (conversation_id, created_at DESC)
    WHERE conversation_id IS NOT NULL;
