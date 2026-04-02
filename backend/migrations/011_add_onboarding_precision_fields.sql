-- Precision question phase fields for onboarding-native flow.
-- Idempotent; safe to re-run.

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS precision_questions JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS precision_answers JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS precision_status TEXT NOT NULL DEFAULT 'not_started';

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS precision_completed_at TIMESTAMPTZ;

