-- Add website_audit column to store generated website audit text per onboarding session.
-- Allows restoring the website_audit stage on refresh without re-generating.
ALTER TABLE onboarding ADD COLUMN IF NOT EXISTS website_audit TEXT NOT NULL DEFAULT '';

