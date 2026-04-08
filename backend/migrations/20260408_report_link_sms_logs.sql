-- Track report-link SMS sends and prevent duplicates per conversation.

CREATE TABLE IF NOT EXISTS report_link_sms_logs (
    id                  BIGSERIAL PRIMARY KEY,
    conversation_id     TEXT NOT NULL,
    user_id             TEXT,
    phone_masked        TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'skipped', 'error')),
    provider            TEXT NOT NULL DEFAULT '2factor',
    provider_message_id TEXT NOT NULL DEFAULT '',
    error               TEXT NOT NULL DEFAULT '',
    sent_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT report_link_sms_logs_conversation_unique UNIQUE (conversation_id)
);

DROP TRIGGER IF EXISTS trg_report_link_sms_logs_updated_at ON report_link_sms_logs;
CREATE TRIGGER trg_report_link_sms_logs_updated_at
    BEFORE UPDATE ON report_link_sms_logs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_user_id
    ON report_link_sms_logs (user_id);

CREATE INDEX IF NOT EXISTS idx_report_link_sms_logs_status
    ON report_link_sms_logs (status, created_at DESC);

INSERT INTO system_config (key, value, description)
VALUES
    ('sms.report_link_enabled', 'false', 'Enable sending deep-analysis report conversation link via SMS after completion'),
    ('sms.report_link_sender_id', '', '2Factor transactional sender ID (required when sms.report_link_enabled=true)'),
    ('sms.report_link_template_name', '', '2Factor template name for report link SMS. Uses VAR1 as conversation URL.')
ON CONFLICT (key) DO NOTHING;

