-- ═══════════════════════════════════════════════════════════════════════════════
-- FULL DATABASE SETUP — life-Sorter-ji (Cloud SQL / PostgreSQL)
-- ═══════════════════════════════════════════════════════════════════════════════
-- Canonical schema for local Postgres / Cloud SQL.
-- Run order: this single file creates everything from scratch.
-- Safe to re-run: all statements use IF NOT EXISTS / OR REPLACE.
-- NOTE: `001_create_user_sessions.sql` is a legacy Supabase-only migration.
--       Do not run both files against the same database.
--
-- Tables:
--   Phase 1 (current app runtime):
--     user_sessions, onboarding, payments, "Persona: founder/owner"
--
--   Phase 2 (Research Agent — asyncpg):
--     agents, agent_config_versions, conversations, messages, skill_calls, plan_runs, token_usage
-- ═══════════════════════════════════════════════════════════════════════════════


-- ─────────────────────────────────────────────────────────────────────────────
-- SHARED UTILITIES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pgcrypto;

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

-- ─────────────────────────────────────────────────────────────────────────────
-- onboarding
-- Phase 1 journey snapshot: outcome / domain / task and URLs keyed by session_id.
-- session_id is required; user_id optional until linked to an authenticated user.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    session_id      TEXT NOT NULL,
    user_id         TEXT,

    outcome         TEXT,
    domain          TEXT,
    task            TEXT,

    website_url     TEXT,
    gbp_url         TEXT,

    -- Optional: unified Q&A log for replay/debug (separate from RCA transcript)
    questions_answers   JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Evolving RCA question/answer history (Phase 1 diagnostic transcript)
    rca_qa          JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Phase 1 scale/business-profile answers (mirrors user_sessions.business_profile)
    scale_answers   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Gap questions (if playbook needs more context)
    gap_questions   JSONB NOT NULL DEFAULT '[]'::jsonb,
    gap_answers     TEXT NOT NULL DEFAULT '',

    -- RCA completion artifacts (used by playbook prompts)
    rca_summary     TEXT NOT NULL DEFAULT '',
    rca_handoff     TEXT NOT NULL DEFAULT '',

    -- Precision phase (post-RCA refinement before playbook)
    precision_questions   JSONB NOT NULL DEFAULT '[]'::jsonb,
    precision_answers     JSONB NOT NULL DEFAULT '[]'::jsonb,
    precision_status      TEXT NOT NULL DEFAULT 'not_started',
    precision_completed_at TIMESTAMPTZ,

    -- Playbook state (DB-backed, avoids session_store)
    playbook_status     TEXT NOT NULL DEFAULT 'not_started',
    playbook_started_at TIMESTAMPTZ,
    playbook_completed_at TIMESTAMPTZ,
    playbook_error      TEXT NOT NULL DEFAULT '',

    -- Pointers to persisted subsystems
    crawl_run_id     UUID,
    crawl_cache_key  TEXT,
    playbook_run_id  UUID,

    onboarding_completed_at TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_session_id
    ON onboarding (session_id);

CREATE INDEX IF NOT EXISTS idx_onboarding_user_id
    ON onboarding (user_id)
    WHERE user_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_onboarding_updated_at ON onboarding;
CREATE TRIGGER trg_onboarding_updated_at
    BEFORE UPDATE ON onboarding
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE onboarding IS
    'Onboarding flow selections and URLs per session; user_id nullable until identity is linked.';

-- ─────────────────────────────────────────────────────────────────────────────
-- crawl_cache / crawl_runs
-- Crawl persistence for reuse across sessions (cache) + per-request audit (runs).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS crawl_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_url  TEXT NOT NULL,
    crawler_version TEXT NOT NULL DEFAULT 'v1',
    crawl_raw       JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawl_summary   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_crawl_cache_url_version
    ON crawl_cache (normalized_url, crawler_version);

DROP TRIGGER IF EXISTS trg_crawl_cache_updated_at ON crawl_cache;
CREATE TRIGGER trg_crawl_cache_updated_at
    BEFORE UPDATE ON crawl_cache
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS crawl_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    user_id         UUID,
    input_url       TEXT NOT NULL,
    normalized_url  TEXT NOT NULL,
    url_type        TEXT NOT NULL DEFAULT 'website',
    status          TEXT NOT NULL DEFAULT 'running',
    cache_hit       BOOLEAN NOT NULL DEFAULT FALSE,
    crawl_cache_id  UUID REFERENCES crawl_cache(id) ON DELETE SET NULL,
    error           TEXT NOT NULL DEFAULT '',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_session_id
    ON crawl_runs (session_id);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_user_id
    ON crawl_runs (user_id);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_normalized_url
    ON crawl_runs (normalized_url);

DROP TRIGGER IF EXISTS trg_crawl_runs_updated_at ON crawl_runs;
CREATE TRIGGER trg_crawl_runs_updated_at
    BEFORE UPDATE ON crawl_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ─────────────────────────────────────────────────────────────────────────────
-- playbook_runs
-- Persist playbook generation outputs independent of session_store.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS playbook_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    user_id         UUID,
    status          TEXT NOT NULL DEFAULT 'running',
    error           TEXT NOT NULL DEFAULT '',
    onboarding_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawl_snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb,
    context_brief   TEXT NOT NULL DEFAULT '',
    icp_card        TEXT NOT NULL DEFAULT '',
    playbook        TEXT NOT NULL DEFAULT '',
    website_audit   TEXT NOT NULL DEFAULT '',
    latencies       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_session_id
    ON playbook_runs (session_id);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_user_id
    ON playbook_runs (user_id);

DROP TRIGGER IF EXISTS trg_playbook_runs_updated_at ON playbook_runs;
CREATE TRIGGER trg_playbook_runs_updated_at
    BEFORE UPDATE ON playbook_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ─────────────────────────────────────────────────────────────────────────────
-- payments
-- JusPay/HDFC payment lifecycle records, linked to session_id.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              TEXT REFERENCES user_sessions(session_id),

    order_id                TEXT UNIQUE NOT NULL,
    juspay_order_id         TEXT,

    amount                  NUMERIC(10,2) NOT NULL,
    currency                TEXT DEFAULT 'INR',
    status                  TEXT DEFAULT 'CREATED',

    customer_email          TEXT,
    customer_phone          TEXT,

    txn_id                  TEXT,
    payment_method          TEXT,
    payment_method_type     TEXT,

    refund_amount           NUMERIC(10,2),
    udf1                    TEXT,
    udf2                    TEXT,

    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payments_session_id
    ON payments (session_id);

CREATE INDEX IF NOT EXISTS idx_payments_order_id
    ON payments (order_id);

CREATE INDEX IF NOT EXISTS idx_payments_created_at
    ON payments (created_at DESC);

DROP TRIGGER IF EXISTS trg_payments_updated_at ON payments;
CREATE TRIGGER trg_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE payments IS
    'Payment orders and status tracking for Stage 2 access (JusPay/HDFC).';

-- ─────────────────────────────────────────────────────────────────────────────
-- "Persona: founder/owner"
-- External knowledge table provided by product team.
-- NOTE: table name contains special chars; keep quoted exactly for compatibility.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS "Persona: founder/owner" (
    id                      BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    created_at              TIMESTAMPTZ DEFAULT now(),

    problem_statement       TEXT NOT NULL,
    scenario_discussed      TEXT NOT NULL,

    root_cause_category     TEXT NOT NULL,
    priority_level          TEXT NOT NULL,
    confidence_level        TEXT NOT NULL,

    business_impact_tags    TEXT NOT NULL,
    early_warning_signals   TEXT NOT NULL,
    common_misfixes         TEXT NOT NULL,

    solution_strategy       JSONB NOT NULL DEFAULT '{}'::jsonb,
    tools_referenced        TEXT NOT NULL,
    implementation_phases   JSONB NOT NULL DEFAULT '[]'::jsonb,

    primary_owner           TEXT NOT NULL,
    automation_potential    TEXT NOT NULL,

    source_platform         TEXT NOT NULL,
    source_context          TEXT NOT NULL
);

COMMENT ON TABLE "Persona: founder/owner" IS
    'Founder/owner persona KB rows used for strategy diagnostics and recommendations.';

-- ─────────────────────────────────────────────────────────────────────────────
-- NOTE:
-- The current product is session-centric. `user_sessions` already stores the
-- authenticated identity snapshot (Google/OTP fields) used by the app today.
-- A separate `users` table was added later as part of a future accounts/billing
-- design, but that model is not used by the current codebase and duplicates the
-- concept of "user" for now.
--
-- To keep the local Postgres schema aligned with the running app, the unused
-- accounts/billing tables are intentionally omitted from this canonical setup:
--   users, plans, subscriptions, usage_quotas, user_consents, audit_logs
--
-- If/when the app is refactored to a true account-centric model, those tables
-- should be introduced in a dedicated migration with matching application code.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- agent_config_versions
-- Versioned snapshots of agent configs/prompts for rollback/audit.
-- ─────────────────────────────────────────────────────────────────────────────
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

-- ─────────────────────────────────────────────────────────────────────────────
-- agent_config_versions
-- Versioned snapshots of agent configs/prompts for rollback/audit.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_config_versions (
    id                      BIGSERIAL PRIMARY KEY,
    agent_id                TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version                 INTEGER NOT NULL,
    config_snapshot         JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes                   TEXT NOT NULL DEFAULT '',
    created_by_session_id   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, version)
);

CREATE INDEX IF NOT EXISTS idx_agent_config_versions_agent
    ON agent_config_versions (agent_id, version DESC);

COMMENT ON TABLE agent_config_versions IS
    'Version history for agent settings/prompts (for traceability and rollback).';

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
    agent_id            TEXT NOT NULL,
    session_id          TEXT,
    user_id             TEXT,
    title               TEXT,
    last_stage_outputs  JSONB NOT NULL DEFAULT '{}'::JSONB,
    last_output_file    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS session_id TEXT;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS user_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversations_agent_id_fkey'
          AND conrelid = 'conversations'::regclass
    ) THEN
        ALTER TABLE conversations
            DROP CONSTRAINT conversations_agent_id_fkey;
    END IF;

    ALTER TABLE conversations
        ADD CONSTRAINT conversations_agent_id_fkey
        FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE RESTRICT;
EXCEPTION
    WHEN undefined_table THEN
        NULL;
    WHEN duplicate_object THEN
        NULL;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_conversations_agent_id
    ON conversations (agent_id);

CREATE INDEX IF NOT EXISTS idx_conversations_session_id
    ON conversations (session_id);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id
    ON conversations (user_id);

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
    streamed_text   TEXT        NOT NULL DEFAULT '',
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

ALTER TABLE skill_calls
    ADD COLUMN IF NOT EXISTS streamed_text TEXT NOT NULL DEFAULT '';

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
                                CHECK (status IN ('draft', 'approved', 'running', 'executing', 'done', 'error', 'cancelled')),
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
    session_id      TEXT,
    model           TEXT        NOT NULL DEFAULT '',
    input_tokens    INTEGER     NOT NULL DEFAULT 0,
    output_tokens   INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE token_usage
    ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_token_usage_message_id
    ON token_usage (message_id);

CREATE INDEX IF NOT EXISTS idx_token_usage_session_id
    ON token_usage (session_id);

COMMENT ON TABLE token_usage IS
    'LLM token usage per assistant message, one row per model call.';

-- ─────────────────────────────────────────────────────────────────────────────
-- Guest chat tables (pre-auth flow)
-- Keep unauthenticated records separated so promotion can be audited.
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

-- ─────────────────────────────────────────────────────────────────────────────
-- users / system_config / otp_provider_logs (independent auth runtime)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number          TEXT UNIQUE,
    email                 TEXT UNIQUE,
    name                  TEXT NOT NULL DEFAULT '',
    auth_provider         TEXT NOT NULL DEFAULT 'otp',
    onboarding_session_id TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_onboarding_session_id
    ON users (onboarding_session_id);

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS system_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_system_config_updated_at ON system_config;
CREATE TRIGGER trg_system_config_updated_at
    BEFORE UPDATE ON system_config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

INSERT INTO system_config (key, value, description)
VALUES
    ('auth.otp_expiry_seconds', '300', 'OTP expiry in seconds'),
    ('auth.otp_bypass_code', '000000', 'Fixed OTP code used when bypass mode is enabled'),
    ('auth.otp_bypass_enabled', 'false', 'Enable OTP bypass for local/dev testing'),
    ('auth.otp_send_sms_enabled', 'true', 'If false, OTP is generated and stored but SMS send is skipped')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS otp_provider_logs (
    id                   BIGSERIAL PRIMARY KEY,
    action               TEXT NOT NULL,
    provider             TEXT NOT NULL DEFAULT '2factor',
    phone_masked         TEXT NOT NULL DEFAULT '',
    request_url          TEXT NOT NULL DEFAULT '',
    response_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_session_id  TEXT NOT NULL DEFAULT '',
    success              BOOLEAN NOT NULL DEFAULT FALSE,
    error                TEXT NOT NULL DEFAULT '',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_otp_provider_logs_created_at
    ON otp_provider_logs (created_at DESC);



-- ═══════════════════════════════════════════════════════════════════════════════
-- END OF SETUP
-- ═══════════════════════════════════════════════════════════════════════════════
