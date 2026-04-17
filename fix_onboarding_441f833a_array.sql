-- Fix onboarding 441f833a-0a61-411b-8c03-4ad590b75878 by linking reused pages

BEGIN;

-- Show current state
SELECT
    '=== BEFORE ===' as status,
    id,
    website_url,
    array_length(scraped_page_ids, 1) as page_count,
    scraped_page_ids
FROM onboarding
WHERE id = '441f833a-0a61-411b-8c03-4ad590b75878';

-- Update to include the curiousjr.com pages that were reused
-- These are the pages from onboarding 91d715e1-42ee-42b9-b11b-7ed9755122d0
UPDATE onboarding
SET scraped_page_ids = (
    SELECT array_agg(id ORDER BY created_at)
    FROM scraped_pages
    WHERE url IN (
        'https://curiousjr.com/',
        'https://www.curiousjr.com/in/school-curriculum/class-7',
        'https://www.curiousjr.com/in/school-curriculum/class-5',
        'https://www.curiousjr.com/in/mental-maths/class-8',
        'https://www.curiousjr.com/in/english-cambridge/preliminary'
    )
    AND onboarding_id = '91d715e1-42ee-42b9-b11b-7ed9755122d0'
)
WHERE id = '441f833a-0a61-411b-8c03-4ad590b75878';

-- Show new state
SELECT
    '=== AFTER ===' as status,
    id,
    website_url,
    array_length(scraped_page_ids, 1) as page_count,
    scraped_page_ids
FROM onboarding
WHERE id = '441f833a-0a61-411b-8c03-4ad590b75878';

-- Verify we can query the pages
SELECT
    '=== PAGES ===' as status,
    sp.id,
    sp.url,
    sp.page_title
FROM onboarding o
JOIN scraped_pages sp ON sp.id = ANY(o.scraped_page_ids)
WHERE o.id = '441f833a-0a61-411b-8c03-4ad590b75878'
ORDER BY sp.created_at;

COMMIT;

