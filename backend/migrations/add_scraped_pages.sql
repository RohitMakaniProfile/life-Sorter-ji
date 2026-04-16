-- Drop the existing table if it has wrong schema
DROP TABLE IF EXISTS scraped_pages;

-- Create scraped_pages table with correct schema
CREATE TABLE scraped_pages (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    raw TEXT,
    markdown TEXT,
    skill_call_id INTEGER,
    conversation_id UUID,
    onboarding_id UUID,
    user_id UUID,
    message_id UUID,
    page_title TEXT,
    status_code INTEGER,
    crawl_depth INTEGER,
    content_type TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url ON scraped_pages(url);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_skill_call_id ON scraped_pages(skill_call_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_conversation_id ON scraped_pages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_onboarding_id ON scraped_pages(onboarding_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_user_id ON scraped_pages(user_id);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_created_at ON scraped_pages(created_at DESC);

