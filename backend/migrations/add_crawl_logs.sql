-- Add crawl_status and error columns to scraped_pages
ALTER TABLE scraped_pages ADD COLUMN IF NOT EXISTS crawl_status TEXT DEFAULT 'done';
ALTER TABLE scraped_pages ADD COLUMN IF NOT EXISTS error TEXT;

-- Create crawl_logs table for per-onboarding crawl error/event logging
CREATE TABLE IF NOT EXISTS crawl_logs (
    id SERIAL PRIMARY KEY,
    onboarding_id UUID,
    user_id UUID,
    level TEXT NOT NULL DEFAULT 'info',   -- 'info' | 'warn' | 'error'
    source TEXT NOT NULL DEFAULT 'crawl', -- 'crawl_task' | 'scraper' | 'summarizer' | etc.
    message TEXT NOT NULL,
    raw JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crawl_logs_onboarding_id ON crawl_logs(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_crawl_logs_user_id ON crawl_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_crawl_logs_created_at ON crawl_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_crawl_status ON scraped_pages(crawl_status);