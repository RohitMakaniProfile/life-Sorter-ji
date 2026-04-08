-- Extend token_usage for admin spend analytics
-- Adds conversation_id/user_id, decoded model fields, and backend-authoritative costs.

ALTER TABLE token_usage
    ADD COLUMN IF NOT EXISTS conversation_id TEXT,
    ADD COLUMN IF NOT EXISTS user_id TEXT,
    ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS model_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS cost_inr NUMERIC(12,2);

-- Backfill stage/provider/model_name from legacy encoded token_usage.model (stage||provider||model).
UPDATE token_usage
SET
    stage = COALESCE(NULLIF(split_part(model, '||', 1), ''), stage),
    provider = COALESCE(NULLIF(split_part(model, '||', 2), ''), provider),
    model_name = COALESCE(NULLIF(split_part(model, '||', 3), ''), model_name)
WHERE model LIKE '%||%';

-- For rows where model is not encoded, treat it as model_name.
UPDATE token_usage
SET model_name = COALESCE(NULLIF(model, ''), model_name)
WHERE (model_name IS NULL OR model_name = '')
  AND model IS NOT NULL
  AND model <> ''
  AND model NOT LIKE '%||%';

-- Backfill conversation_id via messages.message->>'messageId' (indexed in schema).
UPDATE token_usage tu
SET conversation_id = m.conversation_id
FROM messages m
WHERE (tu.conversation_id IS NULL OR tu.conversation_id = '')
  AND (m.message->>'messageId') = tu.message_id;

-- Backfill user_id via conversations.
UPDATE token_usage tu
SET user_id = c.user_id
FROM conversations c
WHERE tu.conversation_id = c.id
  AND (tu.user_id IS NULL OR tu.user_id = '')
  AND c.user_id IS NOT NULL
  AND BTRIM(c.user_id::text) <> '';

CREATE INDEX IF NOT EXISTS idx_token_usage_user_id_created_at
    ON token_usage (user_id, created_at DESC)
    WHERE user_id IS NOT NULL AND BTRIM(user_id) <> '';

CREATE INDEX IF NOT EXISTS idx_token_usage_conversation_id_created_at
    ON token_usage (conversation_id, created_at DESC)
    WHERE conversation_id IS NOT NULL AND BTRIM(conversation_id) <> '';

