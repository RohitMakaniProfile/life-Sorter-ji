-- ═══════════════════════════════════════════════════════════════
-- MIGRATION 001 — Create user_sessions table
-- ═══════════════════════════════════════════════════════════════
-- LEGACY / SUPABASE-ONLY:
-- This file predates `cloud_sql_full_setup.sql`, which is now the canonical
-- full schema for local Postgres / Cloud SQL.
-- Do not run both files against the same database.
--
-- Stores the complete flow for every user session:
--   Auth (Google / OTP) → Q1-Q3 → RCA diagnostic → recommendations
--
-- Run this in the Supabase SQL Editor:
--   Dashboard → SQL Editor → New Query → Paste & Run
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS user_sessions (
    -- Primary key
    id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,

    -- App session identifier (matches backend SessionContext.session_id)
    session_id      text UNIQUE NOT NULL,

    -- Timestamps
    created_at      timestamptz DEFAULT now() NOT NULL,
    updated_at      timestamptz DEFAULT now() NOT NULL,

    -- ── Auth & Identity ─────────────────────────────────────────
    google_id       text,
    google_email    text,
    google_name     text,
    google_avatar_url text,
    mobile_number   text,
    otp_verified    boolean DEFAULT false,
    auth_provider   text,               -- 'google', 'otp', 'both'
    auth_completed_at timestamptz,

    -- ── Flow Stage ──────────────────────────────────────────────
    stage           text DEFAULT 'outcome',
    flow_completed  boolean DEFAULT false,

    -- ── Static Questions (Q1-Q3) ────────────────────────────────
    outcome         text,               -- Q1: growth bucket key
    outcome_label   text,               -- Q1: display label
    domain          text,               -- Q2: sub-category
    task            text,               -- Q3: specific task

    -- ── Full Q&A History ────────────────────────────────────────
    questions_answers jsonb DEFAULT '[]'::jsonb,
    -- Array of {question, answer, question_type, timestamp}

    -- ── Website & Crawl ─────────────────────────────────────────
    website_url     text,
    gbp_url         text,
    crawl_summary   jsonb DEFAULT '{}'::jsonb,
    audience_insights jsonb DEFAULT '{}'::jsonb,

    -- ── Business Profile (Scale Questions) ──────────────────────
    business_profile jsonb DEFAULT '{}'::jsonb,

    -- ── RCA Diagnostic ──────────────────────────────────────────
    rca_history     jsonb DEFAULT '[]'::jsonb,
    rca_summary     text,
    rca_complete    boolean DEFAULT false,

    -- ── Recommendations ─────────────────────────────────────────
    early_recommendations jsonb DEFAULT '[]'::jsonb,
    final_recommendations jsonb DEFAULT '[]'::jsonb,

    -- ── Persona & Context ───────────────────────────────────────
    persona_doc_name text,
    llm_call_log    jsonb DEFAULT '[]'::jsonb,
    -- Array of {service, model, purpose, latency_ms, timestamp}

    -- ── Client Metadata ─────────────────────────────────────────
    ip_address      text,
    user_agent      text,
    referrer        text,
    utm_source      text,
    utm_medium      text,
    utm_campaign    text
);

-- ── Indexes ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_user_sessions_google_email
    ON user_sessions (google_email);

CREATE INDEX IF NOT EXISTS idx_user_sessions_mobile_number
    ON user_sessions (mobile_number);

CREATE INDEX IF NOT EXISTS idx_user_sessions_created_at
    ON user_sessions (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_sessions_stage
    ON user_sessions (stage);

-- ── Auto-update updated_at on every row change ──────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_sessions_updated_at ON user_sessions;
CREATE TRIGGER trg_user_sessions_updated_at
    BEFORE UPDATE ON user_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ── Row Level Security ──────────────────────────────────────────
-- Enable RLS but allow service-role (backend) full access.
-- The anon key can only read its own session by session_id.
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;

-- Backend (service_role) can do everything
DROP POLICY IF EXISTS "service_role_full_access" ON user_sessions;
CREATE POLICY "service_role_full_access"
    ON user_sessions
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Anon key: read-only, only own session
DROP POLICY IF EXISTS "anon_read_own_session" ON user_sessions;
CREATE POLICY "anon_read_own_session"
    ON user_sessions
    FOR SELECT
    USING (true);

COMMENT ON TABLE user_sessions IS 'Complete flow data for every user session: auth, QA, RCA diagnostic, recommendations, and metadata.';
