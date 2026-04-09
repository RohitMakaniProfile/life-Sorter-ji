CREATE TABLE IF NOT EXISTS report_link_sms_logs (
    id BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    provider_message_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_user_id
    ON report_link_sms_logs (user_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_report_link_sms_logs_updated_at ON report_link_sms_logs;
CREATE TRIGGER trg_report_link_sms_logs_updated_at
    BEFORE UPDATE ON report_link_sms_logs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

INSERT INTO system_config (key, value, type, description)
VALUES
    ('sms.report_link_enabled', 'false', 'boolean', 'Send deep-analysis report link via SMS after completion'),
    ('sms.report_link_sender_id', '', 'string', '2Factor sender id for report link SMS'),
    ('sms.report_link_template_name', '', 'string', '2Factor template name for report link SMS')
ON CONFLICT (key) DO NOTHING;
