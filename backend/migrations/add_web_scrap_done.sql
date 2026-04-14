-- Add web_scrap_done column to onboarding table
-- When TRUE, the website URL has been fully scraped (5+ pages) and crawling can be skipped.
ALTER TABLE onboarding ADD COLUMN IF NOT EXISTS web_scrap_done BOOLEAN NOT NULL DEFAULT FALSE;