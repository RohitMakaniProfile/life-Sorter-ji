-- Website audit LLM call logs
-- Stores every generate_website_audit() call (success and failure)
-- for admin inspection.

CREATE TABLE IF NOT EXISTS website_audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    onboarding_id   UUID        REFERENCES onboarding(id) ON DELETE SET NULL,
    model           TEXT        NOT NULL DEFAULT '',
    input_payload   JSONB,          -- system_prompt + user_payload
    output          TEXT,           -- full LLM output (may be empty on error)
    success         BOOLEAN     NOT NULL DEFAULT FALSE,
    error_msg       TEXT,
    input_tokens    INT         NOT NULL DEFAULT 0,
    output_tokens   INT         NOT NULL DEFAULT 0,
    latency_ms      INT         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_audit_logs_onboarding_id
    ON website_audit_logs (onboarding_id);

CREATE INDEX IF NOT EXISTS idx_website_audit_logs_created_at
    ON website_audit_logs (created_at DESC);