-- Migration: Add scraped_page_ids array to onboarding table
-- Production-safe version without COMMENT (which requires ownership)

-- Add the new column
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS scraped_page_ids INTEGER[] DEFAULT '{}';

-- Create an index for faster lookups
CREATE INDEX IF NOT EXISTS idx_onboarding_scraped_page_ids
ON onboarding USING GIN (scraped_page_ids);

-- Populate existing onboardings with their scraped pages
UPDATE onboarding o
SET scraped_page_ids = COALESCE(
    (
        SELECT array_agg(sp.id ORDER BY sp.created_at)
        FROM scraped_pages sp
        WHERE sp.onboarding_id = o.id
    ),
    '{}'::INTEGER[]
)
WHERE scraped_page_ids = '{}' OR scraped_page_ids IS NULL;

