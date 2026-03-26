-- ═══════════════════════════════════════════════════════════════════════════════
-- FULL DATABASE SETUP — life-Sorter-ji (Cloud SQL / PostgreSQL)
-- ═══════════════════════════════════════════════════════════════════════════════
-- Run order: this single file creates everything from scratch.
-- Safe to re-run: all statements use IF NOT EXISTS / OR REPLACE.
--
-- Tables:
--   Phase 1 (Supabase → Cloud SQL):
--     user_sessions, payments, "Persona: founder/owner"
--     users, plans, subscriptions, usage_quotas, user_consents, audit_logs
--
--   Phase 2 (Research Agent — asyncpg):
--     agents, agent_config_versions, conversations, messages, skill_calls, plan_runs, token_usage
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
-- leads
-- Captures inbound leads from the website flow.
-- This replaces the old Supabase `leads` table.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS leads (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    domain                   TEXT,
    website_url              TEXT,

    individual_type          TEXT,
    tech_competency_level    INTEGER,
    timeline_urgency         TEXT,
    micro_solutions_tried    BOOLEAN,
    problem_description      TEXT,

    lead_score               INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'new'
);

CREATE INDEX IF NOT EXISTS idx_leads_created_at
    ON leads (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_leads_domain
    ON leads (domain);

CREATE INDEX IF NOT EXISTS idx_leads_status
    ON leads (status);

DROP TRIGGER IF EXISTS trg_leads_updated_at ON leads;
CREATE TRIGGER trg_leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE leads IS
    'Inbound leads captured from the guided flow. Formerly stored in Supabase.';


-- ─────────────────────────────────────────────────────────────────────────────
-- lead_conversations
-- Stores a lead’s conversation transcript + recommendations JSON.
-- Replaces old Supabase `conversations` table used by leads (NOT Phase2).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id          UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    messages         JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations  JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_conversations_lead_id
    ON lead_conversations (lead_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_lead_conversations_updated_at ON lead_conversations;
CREATE TRIGGER trg_lead_conversations_updated_at
    BEFORE UPDATE ON lead_conversations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE lead_conversations IS
    'Lead flow transcripts + recommendations. Formerly stored in Supabase conversations.';

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
-- users
-- Canonical user account/profile table.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                   TEXT UNIQUE,
    phone                   TEXT UNIQUE,
    full_name               TEXT NOT NULL DEFAULT '',
    avatar_url              TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'suspended', 'deleted')),
    auth_provider           TEXT NOT NULL DEFAULT 'unknown',
    email_verified_at       TIMESTAMPTZ,
    phone_verified_at       TIMESTAMPTZ,
    last_login_at           TIMESTAMPTZ,
    timezone                TEXT NOT NULL DEFAULT 'UTC',
    locale                  TEXT NOT NULL DEFAULT 'en',
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_status
    ON users (status);

CREATE INDEX IF NOT EXISTS idx_users_created_at
    ON users (created_at DESC);

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE users IS
    'Canonical user profile/accounts table for auth identity and preferences.';

-- Optional linkage from flow sessions to users
ALTER TABLE user_sessions
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id
    ON user_sessions (user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- plans
-- Purchasable/visible plans shown in UI.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS plans (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                    TEXT UNIQUE NOT NULL,   -- e.g. starter_monthly
    name                    TEXT NOT NULL,
    description             TEXT NOT NULL DEFAULT '',
    currency                TEXT NOT NULL DEFAULT 'INR',
    price_amount            NUMERIC(10,2) NOT NULL DEFAULT 0,
    billing_interval        TEXT NOT NULL DEFAULT 'month'
                                CHECK (billing_interval IN ('day', 'week', 'month', 'quarter', 'year', 'one_time')),
    is_visible              BOOLEAN NOT NULL DEFAULT TRUE,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order              INTEGER NOT NULL DEFAULT 0,
    features                JSONB NOT NULL DEFAULT '[]'::jsonb,
    quota_defaults          JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plans_visible_active
    ON plans (is_visible, is_active, sort_order);

DROP TRIGGER IF EXISTS trg_plans_updated_at ON plans;
CREATE TRIGGER trg_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE plans IS
    'Catalog of subscription plans displayed in UI for purchase.';

-- ─────────────────────────────────────────────────────────────────────────────
-- subscriptions
-- User subscription lifecycle and billing state.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id                 UUID NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
    status                  TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('trialing', 'active', 'past_due', 'canceled', 'expired')),
    started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_start    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end      TIMESTAMPTZ,
    cancel_at_period_end    BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at             TIMESTAMPTZ,
    external_subscription_id TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status
    ON subscriptions (user_id, status);

CREATE INDEX IF NOT EXISTS idx_subscriptions_period_end
    ON subscriptions (current_period_end);

DROP TRIGGER IF EXISTS trg_subscriptions_updated_at ON subscriptions;
CREATE TRIGGER trg_subscriptions_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE subscriptions IS
    'User subscription records linked to plans and external billing references.';

-- Optional linkage from payments to subscriptions/plans/users
ALTER TABLE payments
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE payments
    ADD COLUMN IF NOT EXISTS plan_id UUID REFERENCES plans(id) ON DELETE SET NULL;

ALTER TABLE payments
    ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_payments_user_id
    ON payments (user_id);

CREATE INDEX IF NOT EXISTS idx_payments_subscription_id
    ON payments (subscription_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- usage_quotas
-- Metered usage counters by period and metric.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usage_quotas (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id         UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    metric                  TEXT NOT NULL,          -- e.g. agent_runs, tokens, reports
    quota_limit             BIGINT NOT NULL DEFAULT 0,
    used_value              BIGINT NOT NULL DEFAULT 0,
    period_start            TIMESTAMPTZ NOT NULL,
    period_end              TIMESTAMPTZ NOT NULL,
    reset_policy            TEXT NOT NULL DEFAULT 'periodic'
                                CHECK (reset_policy IN ('periodic', 'never', 'manual')),
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, metric, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_usage_quotas_user_metric
    ON usage_quotas (user_id, metric, period_end);

DROP TRIGGER IF EXISTS trg_usage_quotas_updated_at ON usage_quotas;
CREATE TRIGGER trg_usage_quotas_updated_at
    BEFORE UPDATE ON usage_quotas
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE usage_quotas IS
    'Per-user usage limits and counters for billing/entitlement enforcement.';

-- ─────────────────────────────────────────────────────────────────────────────
-- user_consents
-- Consent tracking for legal/privacy and marketing preferences.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_consents (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_type            TEXT NOT NULL,          -- e.g. terms, privacy, marketing_email
    consent_version         TEXT NOT NULL DEFAULT '',
    granted                 BOOLEAN NOT NULL,
    granted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at              TIMESTAMPTZ,
    source                  TEXT NOT NULL DEFAULT 'web',
    ip_address              TEXT,
    user_agent              TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, consent_type, consent_version, granted_at)
);

CREATE INDEX IF NOT EXISTS idx_user_consents_user_type
    ON user_consents (user_id, consent_type, granted_at DESC);

COMMENT ON TABLE user_consents IS
    'Immutable consent event log for compliance and preference tracking.';

-- ─────────────────────────────────────────────────────────────────────────────
-- audit_logs
-- Append-only audit/event log for security/compliance.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id                      BIGSERIAL PRIMARY KEY,
    actor_user_id           UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type              TEXT NOT NULL DEFAULT 'user'
                                CHECK (actor_type IN ('user', 'system', 'service')),
    action                  TEXT NOT NULL,          -- e.g. user.login, payment.refund, agent.run
    entity_type             TEXT NOT NULL DEFAULT '', -- e.g. user, payment, conversation
    entity_id               TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'success'
                                CHECK (status IN ('success', 'failure')),
    request_id              TEXT,
    ip_address              TEXT,
    user_agent              TEXT,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_created
    ON audit_logs (actor_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity
    ON audit_logs (entity_type, entity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_action_created
    ON audit_logs (action, created_at DESC);

COMMENT ON TABLE audit_logs IS
    'Append-only audit trail for account, payment, and agent activity.';


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
    created_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL,
    visibility                      TEXT NOT NULL DEFAULT 'private', -- public | private
    is_locked                        BOOLEAN NOT NULL DEFAULT FALSE, -- predefined/system agent protection
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT FALSE;

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
    created_by_user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
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
    agent_id            TEXT NOT NULL REFERENCES agents (id) ON DELETE SET NULL,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title               TEXT,
    last_stage_outputs  JSONB NOT NULL DEFAULT '{}'::JSONB,
    last_output_file    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_conversations_agent_id
    ON conversations (agent_id);

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
    model           TEXT        NOT NULL DEFAULT '',
    input_tokens    INTEGER     NOT NULL DEFAULT 0,
    output_tokens   INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_usage_message_id
    ON token_usage (message_id);

COMMENT ON TABLE token_usage IS
    'LLM token usage per assistant message, one row per model call.';


-- ─────────────────────────────────────────────────────────────────────────────
-- insight_feedback
-- Per-user thumbs up/down feedback for each insight in a final report message.
-- (Used to improve agent quality over time.)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS insight_feedback (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id      TEXT NOT NULL,
    insight_index   INTEGER NOT NULL,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating          SMALLINT NOT NULL, -- 1 = up, -1 = down
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, message_id, insight_index)
);

CREATE INDEX IF NOT EXISTS idx_insight_feedback_message_id
    ON insight_feedback (message_id);

CREATE INDEX IF NOT EXISTS idx_insight_feedback_conversation_id
    ON insight_feedback (conversation_id);


-- ═══════════════════════════════════════════════════════════════════════════════
-- END OF SETUP
-- ═══════════════════════════════════════════════════════════════════════════════
