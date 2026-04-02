-- Store Phase 1 scale/business-profile answers alongside onboarding selections.
-- JSONB matches `user_sessions.business_profile` shape.

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS scale_answers JSONB NOT NULL DEFAULT '{}'::jsonb;

