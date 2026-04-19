-- ============================================================================
-- Ikshan AI — Full PostgreSQL Schema (Single Source of Truth)
-- ============================================================================
-- Run on a fresh database to create all tables, indexes, and constraints.
-- Last synced: 2026-04-18 (matches ikshan-dev schema)
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Shared trigger function for updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Migration tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS _applied_migrations (
    name       text PRIMARY KEY,
    applied_at timestamp with time zone NOT NULL DEFAULT now()
);

-- ============================================================================
-- USERS
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                text,
    auth_provider        text NOT NULL DEFAULT 'unknown',
    last_login_at        timestamp with time zone,
    created_at           timestamp with time zone NOT NULL DEFAULT now(),
    updated_at           timestamp with time zone NOT NULL DEFAULT now(),
    phone_number         text,
    name                 text NOT NULL DEFAULT '',
    onboarding_session_id text
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email         ON users(email)        WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_number  ON users(phone_number) WHERE phone_number IS NOT NULL;
CREATE INDEX        IF NOT EXISTS idx_users_created_at    ON users(created_at DESC);
CREATE INDEX        IF NOT EXISTS idx_users_onboarding_session_id ON users(onboarding_session_id);
-- legacy constraint kept for backward compat
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email);

CREATE OR REPLACE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- AGENTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS agents (
    id                              text PRIMARY KEY,
    name                            text NOT NULL,
    emoji                           text NOT NULL DEFAULT '🤖',
    description                     text NOT NULL DEFAULT '',
    allowed_skill_ids               text[] NOT NULL DEFAULT '{}',
    skill_selector_context          text NOT NULL DEFAULT '',
    final_output_formatting_context text NOT NULL DEFAULT '',
    created_at                      timestamp with time zone NOT NULL DEFAULT now(),
    updated_at                      timestamp with time zone NOT NULL DEFAULT now(),
    created_by_user_id              uuid REFERENCES users(id) ON DELETE SET NULL,
    visibility                      text NOT NULL DEFAULT 'private',
    is_locked                       boolean NOT NULL DEFAULT false
);

CREATE OR REPLACE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- CONVERSATIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id                  text PRIMARY KEY,
    agent_id            text NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    title               text,
    last_stage_outputs  jsonb NOT NULL DEFAULT '{}',
    last_output_file    text,
    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now(),
    user_id             text,
    type                text NOT NULL DEFAULT 'chat',
    onboarding_id       text,
    session_id          text,
    CONSTRAINT conversations_type_check CHECK (type = ANY (ARRAY['chat', 'onboarding']))
);

CREATE INDEX IF NOT EXISTS idx_conversations_agent_id              ON conversations(agent_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id               ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_session_id            ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_onboarding_id         ON conversations(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_conversations_onboarding_session_id ON conversations(onboarding_id) WHERE onboarding_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_type                  ON conversations(type);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at            ON conversations(updated_at DESC);

CREATE OR REPLACE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- AGENT CONFIG VERSIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_config_versions (
    id                     bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    agent_id               text NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version                integer NOT NULL,
    config_snapshot        jsonb NOT NULL DEFAULT '{}',
    notes                  text NOT NULL DEFAULT '',
    created_by_user_id     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at             timestamp with time zone NOT NULL DEFAULT now(),
    created_by_session_id  text,
    UNIQUE (agent_id, version)
);

CREATE INDEX IF NOT EXISTS idx_agent_config_versions_agent ON agent_config_versions(agent_id, version DESC);

-- ============================================================================
-- MESSAGES
-- ============================================================================
CREATE TABLE IF NOT EXISTS messages (
    conversation_id text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_index   integer NOT NULL,
    role            text NOT NULL,
    content         text NOT NULL DEFAULT '',
    output_file     text,
    message         jsonb NOT NULL DEFAULT '{}',
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, message_index)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id, message_index);
CREATE INDEX IF NOT EXISTS idx_messages_message_id_json ON messages((message->>'messageId'));

-- ============================================================================
-- SKILL CALLS
-- ============================================================================
CREATE TABLE IF NOT EXISTS skill_calls (
    id                    bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    conversation_id       text REFERENCES conversations(id) ON DELETE CASCADE,
    message_id            text,
    skill_id              text NOT NULL,
    run_id                text NOT NULL,
    input                 jsonb NOT NULL DEFAULT '{}',
    streamed_text         text NOT NULL DEFAULT '',
    state                 text NOT NULL DEFAULT 'running',
    output                jsonb NOT NULL DEFAULT '[]',
    error                 text,
    started_at            timestamp with time zone NOT NULL DEFAULT now(),
    ended_at              timestamp with time zone,
    duration_ms           integer,
    created_at            timestamp with time zone NOT NULL DEFAULT now(),
    updated_at            timestamp with time zone NOT NULL DEFAULT now(),
    onboarding_session_id text,
    CONSTRAINT skill_calls_state_check CHECK (state = ANY (ARRAY['running', 'done', 'error'])),
    CONSTRAINT skill_calls_context_check CHECK (
        (conversation_id IS NOT NULL AND onboarding_session_id IS NULL) OR
        (conversation_id IS NULL AND onboarding_session_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_skill_calls_conversation_id       ON skill_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_skill_calls_message_id            ON skill_calls(message_id);
CREATE INDEX IF NOT EXISTS idx_skill_calls_onboarding_session_id ON skill_calls(onboarding_session_id) WHERE onboarding_session_id IS NOT NULL;

CREATE OR REPLACE TRIGGER trg_skill_calls_updated_at
    BEFORE UPDATE ON skill_calls
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- SCRAPED PAGES
-- ============================================================================
CREATE TABLE IF NOT EXISTS scraped_pages (
    id              bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    url             text NOT NULL,
    raw             text NOT NULL,
    markdown        text NOT NULL,
    skill_call_id   bigint REFERENCES skill_calls(id) ON DELETE SET NULL,
    conversation_id text REFERENCES conversations(id) ON DELETE SET NULL,
    onboarding_id   text,
    user_id         text,
    message_id      text,
    page_title      text,
    status_code     integer,
    crawl_depth     integer,
    content_type    text,
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    updated_at      timestamp with time zone NOT NULL DEFAULT now(),
    crawl_status    text DEFAULT 'done',
    error           text
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url             ON scraped_pages(url);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_skill_call_id   ON scraped_pages(skill_call_id)   WHERE skill_call_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scraped_pages_conversation_id ON scraped_pages(conversation_id) WHERE conversation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scraped_pages_onboarding_id   ON scraped_pages(onboarding_id)   WHERE onboarding_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scraped_pages_user_id         ON scraped_pages(user_id)         WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scraped_pages_crawl_status    ON scraped_pages(crawl_status);

CREATE OR REPLACE TRIGGER trg_scraped_pages_updated_at
    BEFORE UPDATE ON scraped_pages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- ONBOARDING
-- ============================================================================
CREATE TABLE IF NOT EXISTS onboarding (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               text,
    outcome               text,
    domain                text,
    task                  text,
    website_url           text,
    gbp_url               text,
    created_at            timestamp with time zone NOT NULL DEFAULT now(),
    updated_at            timestamp with time zone NOT NULL DEFAULT now(),
    scale_answers         jsonb NOT NULL DEFAULT '{}',
    rca_qa                jsonb NOT NULL DEFAULT '[]',
    gap_questions         jsonb NOT NULL DEFAULT '[]',
    gap_answers           text NOT NULL DEFAULT '',
    rca_summary           text NOT NULL DEFAULT '',
    rca_handoff           text NOT NULL DEFAULT '',
    playbook_status       text NOT NULL DEFAULT 'not_started',
    playbook_started_at   timestamp with time zone,
    playbook_completed_at timestamp with time zone,
    playbook_error        text NOT NULL DEFAULT '',
    crawl_run_id          uuid,
    playbook_run_id       uuid,
    questions_answers     jsonb NOT NULL DEFAULT '[]',
    onboarding_completed_at timestamp with time zone,
    crawl_cache_key       text,
    precision_questions   jsonb NOT NULL DEFAULT '[]',
    precision_answers     jsonb NOT NULL DEFAULT '[]',
    precision_status      text NOT NULL DEFAULT 'not_started',
    precision_completed_at timestamp with time zone,
    web_summary           text NOT NULL DEFAULT '',
    business_profile      text NOT NULL DEFAULT '',
    conversation_id       text,
    web_scrap_done        boolean NOT NULL DEFAULT false,
    website_audit         text NOT NULL DEFAULT '',
    scraped_page_ids      integer[] DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_onboarding_user_id         ON onboarding(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_onboarding_conversation_id ON onboarding(conversation_id) WHERE conversation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_onboarding_scraped_page_ids ON onboarding USING GIN (scraped_page_ids);

CREATE OR REPLACE TRIGGER trg_onboarding_updated_at
    BEFORE UPDATE ON onboarding
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- PLAN RUNS
-- ============================================================================
CREATE TABLE IF NOT EXISTS plan_runs (
    id                  text PRIMARY KEY,
    conversation_id     text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id     text NOT NULL,
    plan_message_id     text NOT NULL,
    status              text NOT NULL DEFAULT 'draft',
    plan_markdown       text NOT NULL DEFAULT '',
    plan_json           jsonb NOT NULL DEFAULT '{"steps": []}',
    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now(),
    execution_message_id text,
    error_message       text
);

CREATE INDEX IF NOT EXISTS idx_plan_runs_conversation_id ON plan_runs(conversation_id);

CREATE OR REPLACE TRIGGER trg_plan_runs_updated_at
    BEFORE UPDATE ON plan_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- OTP SESSIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS otp_sessions (
    phone_number text PRIMARY KEY,
    payload      jsonb NOT NULL,
    expires_at   timestamp with time zone NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_otp_sessions_expires_at ON otp_sessions(expires_at);

-- ============================================================================
-- OTP PROVIDER LOGS
-- ============================================================================
CREATE TABLE IF NOT EXISTS otp_provider_logs (
    id                  bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    action              text NOT NULL,
    provider            text NOT NULL DEFAULT '2factor',
    phone_masked        text NOT NULL DEFAULT '',
    request_url         text NOT NULL DEFAULT '',
    response_payload    jsonb NOT NULL DEFAULT '{}',
    provider_session_id text NOT NULL DEFAULT '',
    success             boolean NOT NULL DEFAULT false,
    error               text NOT NULL DEFAULT '',
    created_at          timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_otp_provider_logs_created_at ON otp_provider_logs(created_at DESC);

-- ============================================================================
-- SESSION USER LINKS
-- ============================================================================
CREATE TABLE IF NOT EXISTS session_user_links (
    id         bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    session_id text NOT NULL,
    user_id    text NOT NULL,
    linked_at  timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (session_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_session_user_links_session ON session_user_links(session_id);
CREATE INDEX IF NOT EXISTS idx_session_user_links_user    ON session_user_links(user_id);

-- ============================================================================
-- CRAWL CACHE
-- ============================================================================
CREATE TABLE IF NOT EXISTS crawl_cache (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_url  text NOT NULL,
    crawler_version text NOT NULL DEFAULT 'v1',
    crawl_raw       jsonb NOT NULL DEFAULT '{}',
    crawl_summary   jsonb NOT NULL DEFAULT '{}',
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    updated_at      timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (normalized_url, crawler_version)
);

CREATE OR REPLACE TRIGGER trg_crawl_cache_updated_at
    BEFORE UPDATE ON crawl_cache
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- CRAWL RUNS
-- ============================================================================
CREATE TABLE IF NOT EXISTS crawl_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      text NOT NULL,
    user_id         uuid,
    input_url       text NOT NULL,
    normalized_url  text NOT NULL,
    url_type        text NOT NULL DEFAULT 'website',
    status          text NOT NULL DEFAULT 'running',
    cache_hit       boolean NOT NULL DEFAULT false,
    crawl_cache_id  uuid,
    error           text NOT NULL DEFAULT '',
    started_at      timestamp with time zone NOT NULL DEFAULT now(),
    finished_at     timestamp with time zone,
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    updated_at      timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_session_id     ON crawl_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_crawl_runs_user_id        ON crawl_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_crawl_runs_normalized_url ON crawl_runs(normalized_url);

CREATE OR REPLACE TRIGGER trg_crawl_runs_updated_at
    BEFORE UPDATE ON crawl_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- CRAWL LOGS
-- ============================================================================
CREATE TABLE IF NOT EXISTS crawl_logs (
    id            integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    onboarding_id uuid,
    user_id       uuid,
    level         text NOT NULL DEFAULT 'info',
    source        text NOT NULL DEFAULT 'crawl',
    message       text NOT NULL,
    raw           jsonb,
    created_at    timestamp with time zone DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crawl_logs_onboarding_id ON crawl_logs(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_crawl_logs_user_id       ON crawl_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_crawl_logs_created_at    ON crawl_logs(created_at DESC);

-- ============================================================================
-- GUEST CONVERSATIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS guest_conversations (
    id                 text PRIMARY KEY,
    session_id         text NOT NULL,
    title              text,
    created_at         timestamp with time zone NOT NULL DEFAULT now(),
    updated_at         timestamp with time zone NOT NULL DEFAULT now(),
    promoted_to_user_id text,
    promoted_at        timestamp with time zone
);

CREATE INDEX IF NOT EXISTS idx_guest_conversations_session_id  ON guest_conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_guest_conversations_updated_at  ON guest_conversations(updated_at DESC);

-- ============================================================================
-- GUEST MESSAGES
-- ============================================================================
CREATE TABLE IF NOT EXISTS guest_messages (
    guest_conversation_id text NOT NULL REFERENCES guest_conversations(id) ON DELETE CASCADE,
    message_index         integer NOT NULL,
    role                  text NOT NULL,
    content               text NOT NULL DEFAULT '',
    message               jsonb NOT NULL DEFAULT '{}',
    created_at            timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (guest_conversation_id, message_index)
);

CREATE INDEX IF NOT EXISTS idx_guest_messages_conversation_id ON guest_messages(guest_conversation_id, message_index);

-- ============================================================================
-- GUEST LLM CALLS
-- ============================================================================
CREATE TABLE IF NOT EXISTS guest_llm_calls (
    id                    bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    guest_conversation_id text NOT NULL REFERENCES guest_conversations(id) ON DELETE CASCADE,
    message_id            text NOT NULL,
    model                 text NOT NULL DEFAULT '',
    input_tokens          integer NOT NULL DEFAULT 0,
    output_tokens         integer NOT NULL DEFAULT 0,
    created_at            timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_guest_llm_calls_conversation_id ON guest_llm_calls(guest_conversation_id);
CREATE INDEX IF NOT EXISTS idx_guest_llm_calls_message_id      ON guest_llm_calls(message_id);

-- ============================================================================
-- TOKEN USAGE
-- ============================================================================
CREATE TABLE IF NOT EXISTS token_usage (
    id              bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    message_id      text NOT NULL,
    model           text NOT NULL DEFAULT '',
    input_tokens    integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    session_id      text,
    conversation_id text,
    user_id         text,
    stage           text NOT NULL DEFAULT '',
    provider        text NOT NULL DEFAULT '',
    model_name      text NOT NULL DEFAULT '',
    cost_usd        numeric,
    cost_inr        numeric,
    success         boolean,
    error_msg       text,
    raw_output      text
);

CREATE INDEX IF NOT EXISTS idx_token_usage_message_id          ON token_usage(message_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_session_id          ON token_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_conversation_id_created_at
    ON token_usage(conversation_id, created_at DESC)
    WHERE conversation_id IS NOT NULL AND btrim(conversation_id) <> '';
CREATE INDEX IF NOT EXISTS idx_token_usage_user_id_created_at
    ON token_usage(user_id, created_at DESC)
    WHERE user_id IS NOT NULL AND btrim(user_id) <> '';

-- ============================================================================
-- ADMIN SUBSCRIPTION GRANTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS admin_subscription_grants (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granted_by_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason           text NOT NULL DEFAULT '',
    is_active        boolean NOT NULL DEFAULT true,
    granted_at       timestamp with time zone NOT NULL DEFAULT now(),
    revoked_at       timestamp with time zone,
    revoked_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grants_user       ON admin_subscription_grants(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_subscription_grants_granted_by ON admin_subscription_grants(granted_by_user_id);
CREATE INDEX IF NOT EXISTS idx_admin_subscription_grants_active     ON admin_subscription_grants(is_active) WHERE is_active = true;

-- ============================================================================
-- ADMIN SUBSCRIPTION GRANT LOGS
-- ============================================================================
CREATE TABLE IF NOT EXISTS admin_subscription_grant_logs (
    id             bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    target_user_id uuid NOT NULL,
    action         text NOT NULL,
    admin_user_id  uuid NOT NULL,
    reason         text NOT NULL DEFAULT '',
    created_at     timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grant_logs_target ON admin_subscription_grant_logs(target_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_subscription_grant_logs_admin  ON admin_subscription_grant_logs(admin_user_id, created_at DESC);

-- ============================================================================
-- PLANS
-- ============================================================================
CREATE TABLE IF NOT EXISTS plans (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug               text NOT NULL,
    name               text NOT NULL,
    description        text NOT NULL DEFAULT '',
    price_inr          numeric NOT NULL,
    credits_allocation integer,
    features           jsonb NOT NULL DEFAULT '{}',
    display_order      integer NOT NULL DEFAULT 0,
    active             boolean NOT NULL DEFAULT true,
    created_at         timestamp with time zone NOT NULL DEFAULT now(),
    updated_at         timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (slug)
);

CREATE INDEX IF NOT EXISTS idx_plans_active_order ON plans(active, display_order);

CREATE OR REPLACE TRIGGER trg_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- USER PLAN GRANTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_plan_grants (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id           uuid NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
    order_id          text NOT NULL,
    credits_remaining integer,
    granted_at        timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (order_id)
);

CREATE INDEX IF NOT EXISTS idx_user_plan_grants_user ON user_plan_grants(user_id);
CREATE INDEX IF NOT EXISTS idx_user_plan_grants_plan ON user_plan_grants(plan_id);

-- ============================================================================
-- PAYMENTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS payments (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          text,
    order_id            text NOT NULL,
    juspay_order_id     text,
    amount              numeric NOT NULL,
    currency            text DEFAULT 'INR',
    status              text DEFAULT 'CREATED',
    customer_email      text,
    customer_phone      text,
    txn_id              text,
    payment_method      text,
    payment_method_type text,
    refund_amount       numeric,
    udf1                text,
    udf2                text,
    created_at          timestamp with time zone DEFAULT now(),
    updated_at          timestamp with time zone DEFAULT now(),
    UNIQUE (order_id)
);

CREATE INDEX IF NOT EXISTS idx_payments_order_id   ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_session_id ON payments(session_id);
CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at DESC);

CREATE OR REPLACE TRIGGER trg_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- PAYMENT CHECKOUT CONTEXT
-- ============================================================================
CREATE TABLE IF NOT EXISTS payment_checkout_context (
    order_id   text PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id    uuid NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_checkout_context_user ON payment_checkout_context(user_id);

-- ============================================================================
-- PLAYBOOK RUNS
-- ============================================================================
CREATE TABLE IF NOT EXISTS playbook_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        text NOT NULL,
    user_id           uuid,
    status            text NOT NULL DEFAULT 'running',
    error             text NOT NULL DEFAULT '',
    onboarding_snapshot jsonb NOT NULL DEFAULT '{}',
    crawl_snapshot    jsonb NOT NULL DEFAULT '{}',
    context_brief     text NOT NULL DEFAULT '',
    icp_card          text NOT NULL DEFAULT '',
    playbook          text NOT NULL DEFAULT '',
    website_audit     text NOT NULL DEFAULT '',
    latencies         jsonb NOT NULL DEFAULT '{}',
    created_at        timestamp with time zone NOT NULL DEFAULT now(),
    updated_at        timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_session_id ON playbook_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_playbook_runs_user_id    ON playbook_runs(user_id);

CREATE OR REPLACE TRIGGER trg_playbook_runs_updated_at
    BEFORE UPDATE ON playbook_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- PRODUCTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS products (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    emoji       text NOT NULL DEFAULT '🧩',
    description text NOT NULL DEFAULT '',
    color       text NOT NULL DEFAULT '#857BFF',
    outcome     text NOT NULL,
    domain      text NOT NULL,
    task        text NOT NULL,
    is_active   boolean NOT NULL DEFAULT true,
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamp with time zone NOT NULL DEFAULT now(),
    updated_at  timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_products_active_sort ON products(is_active, sort_order, updated_at DESC);

CREATE OR REPLACE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- PROMPTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS prompts (
    slug        text PRIMARY KEY,
    name        text NOT NULL DEFAULT '',
    content     text NOT NULL DEFAULT '',
    description text NOT NULL DEFAULT '',
    category    text NOT NULL DEFAULT 'general',
    created_at  timestamp with time zone NOT NULL DEFAULT now(),
    updated_at  timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category);

CREATE OR REPLACE TRIGGER trg_prompts_updated_at
    BEFORE UPDATE ON prompts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- SYSTEM CONFIG
-- ============================================================================
CREATE TABLE IF NOT EXISTS system_config (
    key         text PRIMARY KEY,
    value       text NOT NULL DEFAULT '',
    description text NOT NULL DEFAULT '',
    updated_at  timestamp with time zone NOT NULL DEFAULT now(),
    type        text NOT NULL DEFAULT 'string'
);

CREATE INDEX IF NOT EXISTS idx_system_config_type ON system_config(type);

CREATE OR REPLACE TRIGGER trg_system_config_updated_at
    BEFORE UPDATE ON system_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Default config
INSERT INTO system_config (key, value, type, description) VALUES
    ('sms.report_link_enabled', 'false', 'boolean', 'Enable SMS notification for research report completion')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- REPORT LINK SMS LOGS
-- ============================================================================
CREATE TABLE IF NOT EXISTS report_link_sms_logs (
    id                  bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    conversation_id     text NOT NULL,
    user_id             text,
    phone_masked        text NOT NULL DEFAULT '',
    status              text NOT NULL DEFAULT 'pending',
    provider            text NOT NULL DEFAULT '2factor',
    provider_message_id text NOT NULL DEFAULT '',
    error               text NOT NULL DEFAULT '',
    sent_at             timestamp with time zone,
    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (conversation_id),
    CONSTRAINT report_link_sms_logs_status_check
        CHECK (status = ANY (ARRAY['pending', 'sent', 'skipped', 'error']))
);

CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_user_id ON report_link_sms_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_status  ON report_link_sms_logs(status, created_at DESC);

CREATE OR REPLACE TRIGGER trg_report_link_sms_logs_updated_at
    BEFORE UPDATE ON report_link_sms_logs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- TASK STREAM STREAMS
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_stream_streams (
    stream_id    text PRIMARY KEY,
    task_type    text NOT NULL,
    session_id   text NOT NULL DEFAULT '',
    user_id      text NOT NULL DEFAULT '',
    status       text NOT NULL DEFAULT 'running',
    last_seq     integer NOT NULL DEFAULT 0,
    last_event_id bigint,
    created_at   timestamp with time zone NOT NULL DEFAULT now(),
    expires_at   timestamp with time zone NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_stream_streams_expires_at ON task_stream_streams(expires_at);

-- ============================================================================
-- TASK STREAM EVENTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_stream_events (
    id         bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    stream_id  text NOT NULL,
    seq        integer NOT NULL,
    event      jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_task_stream_events_stream_id_id ON task_stream_events(stream_id, id);

-- ============================================================================
-- TASK STREAM MAPS
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_stream_maps (
    id         bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    task_type  text NOT NULL,
    map_kind   text NOT NULL,
    map_key    text NOT NULL,
    stream_id  text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    UNIQUE (task_type, map_kind, map_key)
);

CREATE INDEX IF NOT EXISTS idx_task_stream_maps_expires_at ON task_stream_maps(expires_at);

-- ============================================================================
-- TASK STREAM SPAWN LOCKS
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_stream_spawn_locks (
    lock_key   text PRIMARY KEY,
    expires_at timestamp with time zone NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_stream_spawn_locks_expires_at ON task_stream_spawn_locks(expires_at);

-- ============================================================================
-- WEBSITE AUDIT LOGS
-- ============================================================================
CREATE TABLE IF NOT EXISTS website_audit_logs (
    id            bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    onboarding_id uuid,
    model         text NOT NULL DEFAULT '',
    input_payload jsonb,
    output        text,
    success       boolean NOT NULL DEFAULT false,
    error_msg     text,
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    latency_ms    integer NOT NULL DEFAULT 0,
    created_at    timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_website_audit_logs_onboarding_id ON website_audit_logs(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_website_audit_logs_created_at    ON website_audit_logs(created_at DESC);

-- ============================================================================
-- PERSONA: FOUNDER/OWNER  (seed / reference table)
-- ============================================================================
CREATE TABLE IF NOT EXISTS "Persona: founder/owner" (
    id                    bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    created_at            timestamp with time zone DEFAULT now(),
    problem_statement     text NOT NULL,
    scenario_discussed    text NOT NULL,
    root_cause_category   text NOT NULL,
    priority_level        text NOT NULL,
    confidence_level      text NOT NULL,
    business_impact_tags  text NOT NULL,
    early_warning_signals text NOT NULL,
    common_misfixes       text NOT NULL,
    solution_strategy     jsonb NOT NULL DEFAULT '{}',
    tools_referenced      text NOT NULL,
    implementation_phases jsonb NOT NULL DEFAULT '[]',
    primary_owner         text NOT NULL,
    automation_potential  text NOT NULL,
    source_platform       text NOT NULL,
    source_context        text NOT NULL
);

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================