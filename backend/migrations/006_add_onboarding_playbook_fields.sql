-- Extend onboarding to support playbook flow without session_store/user_sessions.
-- Stores gap Qs/answers, RCA summary/handoff, playbook state, and pointers to crawl/playbook runs.

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS gap_questions JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS gap_answers TEXT NOT NULL DEFAULT '';

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS rca_summary TEXT NOT NULL DEFAULT '';

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS rca_handoff TEXT NOT NULL DEFAULT '';

-- Playbook state machine (DB-backed)
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS playbook_status TEXT NOT NULL DEFAULT 'not_started';

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS playbook_started_at TIMESTAMPTZ;

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS playbook_completed_at TIMESTAMPTZ;

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS playbook_error TEXT NOT NULL DEFAULT '';

-- Pointers to persisted subsystems
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS crawl_run_id UUID;

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS playbook_run_id UUID;

