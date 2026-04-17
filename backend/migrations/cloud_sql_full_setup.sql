-- ============================================================================
-- Ikshan AI - Full PostgreSQL Schema
-- ============================================================================
-- This file contains the complete database schema for a fresh deployment
-- Run this on a new database to set up all tables, indexes, and constraints
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- USERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone_number VARCHAR(20) UNIQUE,
    email VARCHAR(255) UNIQUE,
    name VARCHAR(255),
    auth_provider VARCHAR(50) DEFAULT 'phone',
    onboarding_session_id UUID,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_phone_number ON users(phone_number);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ============================================================================
-- ONBOARDING TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS onboarding (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID,

    -- Journey selection
    outcome VARCHAR(255),
    domain VARCHAR(255),
    task TEXT,

    -- Website and scale
    website_url TEXT,
    gbp_url TEXT,
    scale_answers JSONB DEFAULT '{}'::jsonb,

    -- Website scraping and analysis
    web_scrap_done BOOLEAN NOT NULL DEFAULT FALSE,
    web_summary TEXT DEFAULT '',
    business_profile TEXT DEFAULT '',
    website_audit TEXT NOT NULL DEFAULT '',
    crawl_cache_key VARCHAR(255),
    crawl_run_id UUID,

    -- RCA (Root Cause Analysis)
    rca_qa JSONB DEFAULT '[]'::jsonb,
    rca_summary TEXT DEFAULT '',
    rca_handoff TEXT DEFAULT '',
    questions_answers JSONB DEFAULT '[]'::jsonb,

    -- Gap questions (deprecated but kept for backward compatibility)
    gap_questions JSONB DEFAULT '[]'::jsonb,
    gap_answers TEXT DEFAULT '',

    -- Precision questions (deprecated but kept for backward compatibility)
    precision_questions JSONB DEFAULT '[]'::jsonb,
    precision_answers TEXT DEFAULT '',
    precision_status VARCHAR(50),
    precision_completed_at TIMESTAMP WITH TIME ZONE,

    -- Playbook generation
    playbook_status VARCHAR(50) DEFAULT 'not_started',
    playbook_started_at TIMESTAMP WITH TIME ZONE,
    playbook_completed_at TIMESTAMP WITH TIME ZONE,
    playbook_error TEXT DEFAULT '',
    playbook_run_id UUID,

    -- Linked conversation
    conversation_id UUID,

    -- Completion tracking
    onboarding_completed_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_user_id ON onboarding(user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_session_id ON onboarding(session_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_playbook_status ON onboarding(playbook_status);
CREATE INDEX IF NOT EXISTS idx_onboarding_created_at ON onboarding(created_at DESC);

-- ============================================================================
-- CONVERSATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    onboarding_id UUID REFERENCES onboarding(id) ON DELETE SET NULL,
    session_id UUID,

    -- Conversation metadata
    title VARCHAR(500),
    agent_id VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active',

    -- Message storage
    messages JSONB DEFAULT '[]'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_onboarding_id ON conversations(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_conversations_session_id ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);

-- ============================================================================
-- SESSION LINKS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS session_links (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL UNIQUE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_session_links_session_id ON session_links(session_id);
CREATE INDEX IF NOT EXISTS idx_session_links_user_id ON session_links(user_id);

-- ============================================================================
-- OTP SESSIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS otp_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone_number VARCHAR(20) NOT NULL,
    otp_code VARCHAR(10) NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_otp_sessions_phone_number ON otp_sessions(phone_number);
CREATE INDEX IF NOT EXISTS idx_otp_sessions_expires_at ON otp_sessions(expires_at);

-- ============================================================================
-- OTP LOGS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS otp_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone_number VARCHAR(20) NOT NULL,
    otp_code VARCHAR(10) NOT NULL,
    provider VARCHAR(50) DEFAULT '2factor',
    status VARCHAR(50),
    provider_response TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_otp_logs_phone_number ON otp_logs(phone_number);
CREATE INDEX IF NOT EXISTS idx_otp_logs_created_at ON otp_logs(created_at DESC);

-- ============================================================================
-- SCRAPED PAGES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS scraped_pages (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    raw TEXT,
    markdown TEXT,
    skill_call_id INTEGER,
    conversation_id UUID,
    onboarding_id UUID,
    user_id UUID,
    message_id UUID,
    page_title TEXT,
    status_code INTEGER,
    crawl_depth INTEGER,
    content_type TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url ON scraped_pages(url);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_skill_call_id ON scraped_pages(skill_call_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_conversation_id ON scraped_pages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_onboarding_id ON scraped_pages(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_user_id ON scraped_pages(user_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_created_at ON scraped_pages(created_at DESC);

-- ============================================================================
-- TASK STREAM TABLES
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_stream_streams (
    stream_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    result JSONB,
    error TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_stream_streams_session_id ON task_stream_streams(session_id);
CREATE INDEX IF NOT EXISTS idx_task_stream_streams_task_type ON task_stream_streams(task_type);
CREATE INDEX IF NOT EXISTS idx_task_stream_streams_status ON task_stream_streams(status);
CREATE INDEX IF NOT EXISTS idx_task_stream_streams_created_at ON task_stream_streams(created_at DESC);

CREATE TABLE IF NOT EXISTS task_stream_maps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL,
    stream_id UUID NOT NULL REFERENCES task_stream_streams(stream_id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(session_id, stream_id)
);

CREATE INDEX IF NOT EXISTS idx_task_stream_maps_session_id ON task_stream_maps(session_id);
CREATE INDEX IF NOT EXISTS idx_task_stream_maps_stream_id ON task_stream_maps(stream_id);

CREATE TABLE IF NOT EXISTS task_stream_spawn_locks (
    lock_key VARCHAR(255) PRIMARY KEY,
    acquired_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_stream_spawn_locks_expires_at ON task_stream_spawn_locks(expires_at);

-- ============================================================================
-- AGENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS agents (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    system_prompt TEXT,
    model VARCHAR(100),
    temperature NUMERIC(3,2),
    max_tokens INTEGER,
    tools JSONB DEFAULT '[]'::jsonb,
    config JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_is_active ON agents(is_active);

-- ============================================================================
-- PLANS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    steps JSONB DEFAULT '[]'::jsonb,
    is_template BOOLEAN DEFAULT FALSE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plans_is_template ON plans(is_template);
CREATE INDEX IF NOT EXISTS idx_plans_created_by ON plans(created_by);

-- ============================================================================
-- PLAN RUNS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS plan_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID REFERENCES plans(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    steps_data JSONB DEFAULT '[]'::jsonb,
    result JSONB,
    error TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_runs_plan_id ON plan_runs(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_runs_conversation_id ON plan_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_plan_runs_user_id ON plan_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_plan_runs_status ON plan_runs(status);

-- ============================================================================
-- SKILL CALLS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS skill_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    skill_name VARCHAR(255) NOT NULL,
    parameters JSONB DEFAULT '{}'::jsonb,
    result JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    error TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_calls_conversation_id ON skill_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_skill_calls_skill_name ON skill_calls(skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_calls_status ON skill_calls(status);
CREATE INDEX IF NOT EXISTS idx_skill_calls_created_at ON skill_calls(created_at DESC);

-- ============================================================================
-- TOKEN USAGE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS token_usage (
    id SERIAL PRIMARY KEY,
    message_id TEXT NOT NULL,
    session_id TEXT,
    conversation_id TEXT,
    user_id TEXT,

    -- Model and provider info
    model TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',

    -- Token counts
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,

    -- Cost tracking
    cost_usd NUMERIC(12,6),
    cost_inr NUMERIC(12,2),

    -- Success tracking
    success BOOLEAN,
    error_msg TEXT,
    raw_output TEXT,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_usage_message_id ON token_usage(message_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_session_id ON token_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_conversation_id ON token_usage(conversation_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_user_id ON token_usage(user_id);

-- ============================================================================
-- ADMIN GRANTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS admin_grants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'admin',
    granted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    revoked_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(user_id, role)
);

CREATE INDEX IF NOT EXISTS idx_admin_grants_user_id ON admin_grants(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_grants_role ON admin_grants(role);

-- ============================================================================
-- USER PLAN GRANTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_plan_grants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_name VARCHAR(100) NOT NULL,
    granted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_plan_grants_user_id ON user_plan_grants(user_id);
CREATE INDEX IF NOT EXISTS idx_user_plan_grants_plan_name ON user_plan_grants(plan_name);
CREATE INDEX IF NOT EXISTS idx_user_plan_grants_expires_at ON user_plan_grants(expires_at);

-- ============================================================================
-- PAYMENT CHECKOUT TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS payment_checkout (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    order_id VARCHAR(255) UNIQUE NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'INR',
    status VARCHAR(50) DEFAULT 'pending',
    payment_gateway VARCHAR(50) DEFAULT 'juspay',
    gateway_order_id VARCHAR(255),
    gateway_response JSONB,
    plan_name VARCHAR(100),
    metadata JSONB DEFAULT '{}'::jsonb,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_checkout_user_id ON payment_checkout(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_checkout_order_id ON payment_checkout(order_id);
CREATE INDEX IF NOT EXISTS idx_payment_checkout_status ON payment_checkout(status);

-- ============================================================================
-- PRODUCTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price NUMERIC(12,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'INR',
    plan_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_plan_name ON products(plan_name);

-- ============================================================================
-- PROMPTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS prompts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(255) UNIQUE NOT NULL,
    category VARCHAR(100),
    title VARCHAR(255),
    content TEXT NOT NULL,
    variables JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompts_key ON prompts(key);
CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category);
CREATE INDEX IF NOT EXISTS idx_prompts_is_active ON prompts(is_active);

-- ============================================================================
-- SYSTEM CONFIG TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'string',
    description TEXT,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert default system config values
INSERT INTO system_config (key, value, type, description)
VALUES
    ('sms.report_link_enabled', 'false', 'boolean', 'Enable SMS notification for research report completion')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- REPORT LINK SMS LOGS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS report_link_sms_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    phone_number VARCHAR(20) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    provider_message_id VARCHAR(255),
    error TEXT,
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_conversation_id ON report_link_sms_logs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_user_id ON report_link_sms_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_status ON report_link_sms_logs(status);

-- ============================================================================
-- TRIGGERS FOR updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to all tables with updated_at column
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_onboarding_updated_at BEFORE UPDATE ON onboarding
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversations_updated_at BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scraped_pages_updated_at BEFORE UPDATE ON scraped_pages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_task_stream_streams_updated_at BEFORE UPDATE ON task_stream_streams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_agents_updated_at BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_plans_updated_at BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_plan_runs_updated_at BEFORE UPDATE ON plan_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_skill_calls_updated_at BEFORE UPDATE ON skill_calls
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_plan_grants_updated_at BEFORE UPDATE ON user_plan_grants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payment_checkout_updated_at BEFORE UPDATE ON payment_checkout
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_products_updated_at BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_prompts_updated_at BEFORE UPDATE ON prompts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_system_config_updated_at BEFORE UPDATE ON system_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_report_link_sms_logs_updated_at BEFORE UPDATE ON report_link_sms_logs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================

