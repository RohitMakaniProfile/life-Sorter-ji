-- Google / OTP auth store email or `otp:<session_id>` as user_id — not UUID.
-- If an older DB created these columns as uuid, promotion from /api/v1/auth/google fails.
-- Align with cloud_sql_full_setup.sql (user_id TEXT).
--
-- Drop FKs on user_id first (e.g. to users.id uuid); emails cannot reference uuid ids.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS rel
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) AND NOT a.attisdropped
    WHERE c.contype = 'f'
      AND c.conrelid = ANY (
        ARRAY[
          'public.conversations'::regclass,
          'public.session_user_links'::regclass
        ]
      )
      AND a.attname = 'user_id'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.rel, r.conname);
  END LOOP;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'conversations'
      AND column_name = 'user_id'
      AND udt_name = 'uuid'
  ) THEN
    ALTER TABLE conversations
      ALTER COLUMN user_id TYPE text USING (user_id::text);
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'session_user_links'
      AND column_name = 'user_id'
      AND udt_name = 'uuid'
  ) THEN
    ALTER TABLE session_user_links
      ALTER COLUMN user_id TYPE text USING (user_id::text);
  END IF;
END $$;
