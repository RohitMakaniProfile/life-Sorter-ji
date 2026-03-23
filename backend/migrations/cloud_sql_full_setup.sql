-- ═══════════════════════════════════════════════════════════════════════════════
-- FULL DATABASE SETUP — life-Sorter-ji (Cloud SQL / PostgreSQL)
-- ═══════════════════════════════════════════════════════════════════════════════
-- Run order: this single file creates everything from scratch.
-- Safe to re-run: all statements use IF NOT EXISTS / OR REPLACE.
--
-- Tables:
--   Phase 1 (Supabase → Cloud SQL):
--     user_sessions
--
--   Phase 2 (Research Agent — asyncpg):
--     agents, conversations, messages, skill_calls, plan_runs, token_usage
-- ═══════════════════════════════════════════════════════════════════════════════


-- ─────────────────────────────────────────────────────────────────────────────
-- SHARED UTILITIES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ═══════════════════════════════════════════════════════════════════════════════
-- PHASE 1 — Session / Flow tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- user_sessions
-- Stores the complete guided-flow state for every anonymous / authenticated
-- visitor: auth data, Q1-Q3 answers, RCA history, and final recommendations.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_sessions (
    -- Primary key
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,

    -- App session identifier (matches backend SessionContext.session_id)
    session_id              TEXT UNIQUE NOT NULL,

    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ── Auth & Identity ─────────────────────────────────────────────────────
    google_id               TEXT,
    google_email            TEXT,
    google_name             TEXT,
    google_avatar_url       TEXT,
    mobile_number           TEXT,
    otp_verified            BOOLEAN DEFAULT FALSE,
    auth_provider           TEXT,           -- 'google' | 'otp' | 'both'
    auth_completed_at       TIMESTAMPTZ,

    -- ── Flow Stage ──────────────────────────────────────────────────────────
    stage                   TEXT DEFAULT 'outcome',
    flow_completed          BOOLEAN DEFAULT FALSE,

    -- ── Static Questions (Q1-Q3) ────────────────────────────────────────────
    outcome                 TEXT,           -- Q1: growth bucket key
    outcome_label           TEXT,           -- Q1: display label
    domain                  TEXT,           -- Q2: sub-category
    task                    TEXT,           -- Q3: specific task

    -- ── Full Q&A History ────────────────────────────────────────────────────
    -- Array of {question, answer, question_type, timestamp}
    questions_answers       JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- ── Website & Crawl ─────────────────────────────────────────────────────
    website_url             TEXT,
    gbp_url                 TEXT,
    crawl_summary           JSONB NOT NULL DEFAULT '{}'::JSONB,
    audience_insights       JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- ── Business Profile (Scale Questions) ──────────────────────────────────
    business_profile        JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- ── RCA Diagnostic ──────────────────────────────────────────────────────
    -- Array of {role, content} conversation turns
    rca_history             JSONB NOT NULL DEFAULT '[]'::JSONB,
    rca_summary             TEXT,
    rca_complete            BOOLEAN DEFAULT FALSE,

    -- ── Recommendations ─────────────────────────────────────────────────────
    early_recommendations   JSONB NOT NULL DEFAULT '[]'::JSONB,
    final_recommendations   JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- ── Persona & Context ───────────────────────────────────────────────────
    persona_doc_name        TEXT,
    -- Array of {service, model, purpose, latency_ms, timestamp}
    llm_call_log            JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- ── Client Metadata ─────────────────────────────────────────────────────
    ip_address              TEXT,
    user_agent              TEXT,
    referrer                TEXT,
    utm_source              TEXT,
    utm_medium              TEXT,
    utm_campaign            TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_google_email
    ON user_sessions (google_email);

CREATE INDEX IF NOT EXISTS idx_user_sessions_mobile_number
    ON user_sessions (mobile_number);

CREATE INDEX IF NOT EXISTS idx_user_sessions_created_at
    ON user_sessions (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_sessions_stage
    ON user_sessions (stage);

DROP TRIGGER IF EXISTS trg_user_sessions_updated_at ON user_sessions;
CREATE TRIGGER trg_user_sessions_updated_at
    BEFORE UPDATE ON user_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE user_sessions IS
    'Complete flow data for every user session: auth, Q&A, RCA diagnostic, recommendations, and tracking metadata.';


-- ═══════════════════════════════════════════════════════════════════════════════
-- PHASE 2 — Research Agent tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- agents
-- UI-configurable research agents. Each agent has a set of allowed skills and
-- optional prompt context injected into the orchestrator.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id                              TEXT PRIMARY KEY,
    name                            TEXT NOT NULL,
    emoji                           TEXT NOT NULL DEFAULT '🤖',
    description                     TEXT NOT NULL DEFAULT '',
    allowed_skill_ids               TEXT[] NOT NULL DEFAULT '{}',
    skill_selector_context          TEXT NOT NULL DEFAULT '',
    final_output_formatting_context TEXT NOT NULL DEFAULT '',
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_agents_updated_at ON agents;
CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE agents IS
    'Research agent definitions: skill allowlist, orchestrator prompt context.';

-- Seed default agent (upsert so re-runs are safe)
INSERT INTO agents (
    id, name, emoji, description,
    allowed_skill_ids, skill_selector_context, final_output_formatting_context
) VALUES (
    'research-orchestrator',
    'Business Research',
    '🕵️',
    'Agentic research using website scrapers, social and sentiment skills',
    ARRAY[
        'scrape-bs4',
        'scrape-playwright',
        'scrape-googlebusiness',
        'instagram-sentiment',
        'youtube-sentiment',
        'playstore-sentiment',
        'quora-search',
        'find-platform-handles'
    ],
    '',
    ''
)
ON CONFLICT (id) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- conversations
-- One row per chat session. Linked to an agent. Stores last pipeline outputs
-- so the frontend can resume where it left off.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents (id) ON DELETE SET NULL,
    title               TEXT,
    last_stage_outputs  JSONB NOT NULL DEFAULT '{}'::JSONB,
    last_output_file    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_agent_id
    ON conversations (agent_id);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations (updated_at DESC);

DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
CREATE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE conversations IS
    'Chat sessions. Each conversation belongs to one agent and stores ordered messages.';


-- ─────────────────────────────────────────────────────────────────────────────
-- messages
-- Ordered messages inside a conversation. message_index enforces order and is
-- assigned atomically with an advisory lock to avoid gaps.
-- The `message` JSONB column is the full payload (messageId, skillsCount, etc.).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    message_index   INTEGER     NOT NULL,
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT        NOT NULL DEFAULT '',
    output_file     TEXT,
    -- Full message payload including messageId, skillsCount, kind, planId
    message         JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (conversation_id, message_index)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages (conversation_id, message_index ASC);

-- JSON index for messageId lookups (used by update_message_content)
CREATE INDEX IF NOT EXISTS idx_messages_message_id_json
    ON messages ((message->>'messageId'));

COMMENT ON TABLE messages IS
    'Ordered messages within a conversation. message_index is monotonically increasing per conversation.';


-- ─────────────────────────────────────────────────────────────────────────────
-- skill_calls
-- Tracks every individual skill subprocess invocation: inputs, streaming
-- output events, final state, and duration.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS skill_calls (
    id              BIGSERIAL   PRIMARY KEY,
    conversation_id TEXT        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    message_id      TEXT        NOT NULL,
    skill_id        TEXT        NOT NULL,
    run_id          TEXT        NOT NULL,
    input           JSONB       NOT NULL DEFAULT '{}'::JSONB,
    state           TEXT        NOT NULL DEFAULT 'running'
                                CHECK (state IN ('running', 'done', 'error')),
    -- Array of output event objects: {type, event?, payload?, text?, data?, at}
    output          JSONB       NOT NULL DEFAULT '[]'::JSONB,
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_calls_message_id
    ON skill_calls (message_id);

CREATE INDEX IF NOT EXISTS idx_skill_calls_conversation_id
    ON skill_calls (conversation_id);

DROP TRIGGER IF EXISTS trg_skill_calls_updated_at ON skill_calls;
CREATE TRIGGER trg_skill_calls_updated_at
    BEFORE UPDATE ON skill_calls
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE skill_calls IS
    'Individual skill subprocess invocations: inputs, streaming events, result state, and timing.';


-- ─────────────────────────────────────────────────────────────────────────────
-- plan_runs
-- Two-phase planning: the user approves a plan before the agent executes it.
-- Stores both the markdown shown to the user and the structured JSON steps.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS plan_runs (
    id              TEXT        PRIMARY KEY,
    conversation_id TEXT        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    user_message_id TEXT        NOT NULL,
    plan_message_id TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft', 'approved', 'running', 'done', 'error')),
    plan_markdown   TEXT        NOT NULL DEFAULT '',
    -- {steps: [{id, title, skillId, description, status}]}
    plan_json       JSONB       NOT NULL DEFAULT '{"steps":[]}'::JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_runs_conversation_id
    ON plan_runs (conversation_id);

DROP TRIGGER IF EXISTS trg_plan_runs_updated_at ON plan_runs;
CREATE TRIGGER trg_plan_runs_updated_at
    BEFORE UPDATE ON plan_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE plan_runs IS
    'Two-phase plan execution: user sees and approves a markdown plan before the agent runs it.';


-- ─────────────────────────────────────────────────────────────────────────────
-- token_usage
-- Per-message LLM token accounting across all models (OpenAI, Claude, Gemini).
-- Multiple rows per message (one per LLM call).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_usage (
    id              BIGSERIAL   PRIMARY KEY,
    message_id      TEXT        NOT NULL,
    model           TEXT        NOT NULL DEFAULT '',
    input_tokens    INTEGER     NOT NULL DEFAULT 0,
    output_tokens   INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_usage_message_id
    ON token_usage (message_id);

COMMENT ON TABLE token_usage IS
    'LLM token usage per assistant message, one row per model call.';


-- ═══════════════════════════════════════════════════════════════════════════════
-- END OF SETUP
-- ═══════════════════════════════════════════════════════════════════════════════
