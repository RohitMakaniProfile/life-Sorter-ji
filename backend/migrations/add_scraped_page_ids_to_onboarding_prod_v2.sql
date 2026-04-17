-- Migration: Add scraped_page_ids array to onboarding table
-- Safe version that only creates if not exists

DO $$
BEGIN
    -- Add the new column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'onboarding'
        AND column_name = 'scraped_page_ids'
    ) THEN
        ALTER TABLE onboarding ADD COLUMN scraped_page_ids INTEGER[] DEFAULT '{}';
    END IF;
END $$;

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

