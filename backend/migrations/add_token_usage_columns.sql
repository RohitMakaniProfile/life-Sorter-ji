-- Add missing columns to token_usage table
ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS session_id UUID;
ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS success BOOLEAN;
ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS error_msg TEXT;
ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS raw_output TEXT;

-- Create index on session_id for performance
CREATE INDEX IF NOT EXISTS idx_token_usage_session_id ON token_usage(session_id);

