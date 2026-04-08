-- Add `type` field to system_config
-- Supports typed admin UI editors (e.g. markdown prompts).

ALTER TABLE system_config
ADD COLUMN IF NOT EXISTS type TEXT NOT NULL DEFAULT 'string';

CREATE INDEX IF NOT EXISTS idx_system_config_type
    ON system_config (type);

