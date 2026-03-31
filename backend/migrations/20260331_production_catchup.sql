-- ═══════════════════════════════════════════════════════════════════════════════
-- MIGRATION 20260331 — Production catch-up
-- ═══════════════════════════════════════════════════════════════════════════════
-- Adds missing columns and tables to align production with cloud_sql_full_setup.sql
--
-- Changes:
--   1. conversations.session_id TEXT column + index
--   2. conversations.user_id: drop uuid FK, cast to TEXT
--   3. token_usage.session_id TEXT column + index
--   4. Create missing tables: guest_conversations, guest_messages,
--      guest_llm_calls, session_user_links
-- ═══════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. conversations.session_id
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_session_id
    ON conversations (session_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. conversations.user_id  uuid → text  (drop FK first)
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS rel
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid
                        AND a.attnum = ANY (c.conkey)
                        AND NOT a.attisdropped
    WHERE c.contype = 'f'
      AND c.conrelid = ANY (
            ARRAY[
              'public.conversations'::regclass,
              'public.session_user_links'::regclass
            ]
          )
      AND a.attname = 'user_id'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.rel, r.conname);
  END LOOP;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name   = 'conversations'
      AND column_name  = 'user_id'
      AND udt_name     = 'uuid'
  ) THEN
    ALTER TABLE conversations
      ALTER COLUMN user_id TYPE text USING (user_id::text);
  END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. token_usage.session_id
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE token_usage
    ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_token_usage_session_id
    ON token_usage (session_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Guest chat tables
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guest_conversations (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    title               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_to_user_id TEXT,
    promoted_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_guest_conversations_session_id
    ON guest_conversations (session_id);

CREATE INDEX IF NOT EXISTS idx_guest_conversations_updated_at
    ON guest_conversations (updated_at DESC);

CREATE TABLE IF NOT EXISTS guest_messages (
    guest_conversation_id TEXT        NOT NULL REFERENCES guest_conversations (id) ON DELETE CASCADE,
    message_index         INTEGER     NOT NULL,
    role                  TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content               TEXT        NOT NULL DEFAULT '',
    message               JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guest_conversation_id, message_index)
);

CREATE INDEX IF NOT EXISTS idx_guest_messages_conversation_id
    ON guest_messages (guest_conversation_id, message_index ASC);

CREATE TABLE IF NOT EXISTS guest_llm_calls (
    id                    BIGSERIAL   PRIMARY KEY,
    guest_conversation_id TEXT        NOT NULL REFERENCES guest_conversations (id) ON DELETE CASCADE,
    message_id            TEXT        NOT NULL,
    model                 TEXT        NOT NULL DEFAULT '',
    input_tokens          INTEGER     NOT NULL DEFAULT 0,
    output_tokens         INTEGER     NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guest_llm_calls_conversation_id
    ON guest_llm_calls (guest_conversation_id);

CREATE INDEX IF NOT EXISTS idx_guest_llm_calls_message_id
    ON guest_llm_calls (message_id);

CREATE TABLE IF NOT EXISTS session_user_links (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_session_user_links_session
    ON session_user_links (session_id);

CREATE INDEX IF NOT EXISTS idx_session_user_links_user
    ON session_user_links (user_id);