-- Migration: Add scraped_page_ids array to onboarding table
-- This allows an onboarding to reference multiple scraped pages without duplication

BEGIN;

-- Add the new column
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS scraped_page_ids INTEGER[] DEFAULT '{}';

-- Create an index for faster lookups
CREATE INDEX IF NOT EXISTS idx_onboarding_scraped_page_ids
ON onboarding USING GIN (scraped_page_ids);

-- Add a comment for documentation
COMMENT ON COLUMN onboarding.scraped_page_ids IS
'Array of scraped_pages.id values associated with this onboarding. Pages can be shared across multiple onboardings.';

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

COMMIT;

-- Verification queries:
SELECT
    '=== Migration Complete ===' as status,
    COUNT(*) as onboardings_with_pages
FROM onboarding
WHERE array_length(scraped_page_ids, 1) > 0;

-- Show sample data
SELECT
    id,
    website_url,
    array_length(scraped_page_ids, 1) as page_count,
    scraped_page_ids[1:3] as first_3_page_ids
FROM onboarding
WHERE array_length(scraped_page_ids, 1) > 0
LIMIT 5;

