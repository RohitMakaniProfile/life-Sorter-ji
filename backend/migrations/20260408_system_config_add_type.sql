ALTER TABLE system_config
    ADD COLUMN IF NOT EXISTS type TEXT NOT NULL DEFAULT 'string';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'system_config_type_check'
          AND conrelid = 'public.system_config'::regclass
    ) THEN
        ALTER TABLE system_config ADD CONSTRAINT system_config_type_check
            CHECK (type IN ('string', 'number', 'boolean', 'json', 'markdown'));
    END IF;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_system_config_type
    ON system_config (type);
