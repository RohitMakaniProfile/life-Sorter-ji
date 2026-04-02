-- Decouple onboarding from user_sessions.
-- The onboarding session_id must not require a user_sessions row.

ALTER TABLE onboarding
DROP CONSTRAINT IF EXISTS onboarding_session_id_fkey;

