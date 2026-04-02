-- OTP session payloads when Redis is not configured (Postgres fallback).

CREATE TABLE IF NOT EXISTS otp_sessions (
    otp_session_id  TEXT PRIMARY KEY,
    payload         JSONB NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_otp_sessions_expires_at
    ON otp_sessions (expires_at);
