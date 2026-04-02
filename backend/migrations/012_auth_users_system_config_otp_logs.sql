-- Independent auth foundation:
-- - users table (identity + onboarding link)
-- - system_config key/value store (admin-manageable runtime toggles)
-- - otp_provider_logs (third-party SMS API audit trail)

CREATE TABLE IF NOT EXISTS users (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number          TEXT UNIQUE,
    email                 TEXT UNIQUE,
    name                  TEXT NOT NULL DEFAULT '',
    auth_provider         TEXT NOT NULL DEFAULT 'otp', -- otp | google | both
    onboarding_session_id TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at         TIMESTAMPTZ
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider TEXT NOT NULL DEFAULT 'otp';
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_session_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_number
    ON users (phone_number)
    WHERE phone_number IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
    ON users (email)
    WHERE email IS NOT NULL;

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
    action               TEXT NOT NULL, -- send
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

