-- Migration: add scraped_pages table
-- Safe to re-run (IF NOT EXISTS / DROP TRIGGER IF EXISTS)

CREATE TABLE IF NOT EXISTS scraped_pages (
    id                  BIGSERIAL   PRIMARY KEY,

    -- Core content (all mandatory)
    url                 TEXT        NOT NULL,
    raw                 TEXT        NOT NULL,
    markdown            TEXT        NOT NULL,

    -- Optional provenance links
    skill_call_id       BIGINT      REFERENCES skill_calls(id) ON DELETE SET NULL,
    conversation_id     TEXT        REFERENCES conversations(id) ON DELETE SET NULL,
    onboarding_id       TEXT,
    user_id             TEXT,
    message_id          TEXT,

    -- Page-level metadata
    page_title          TEXT,
    status_code         INTEGER,
    crawl_depth         INTEGER,
    content_type        TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_skill_call_id
    ON scraped_pages (skill_call_id)
    WHERE skill_call_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scraped_pages_conversation_id
    ON scraped_pages (conversation_id)
    WHERE conversation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scraped_pages_onboarding_id
    ON scraped_pages (onboarding_id)
    WHERE onboarding_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scraped_pages_user_id
    ON scraped_pages (user_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url
    ON scraped_pages (url);

DROP TRIGGER IF EXISTS trg_scraped_pages_updated_at ON scraped_pages;
CREATE TRIGGER trg_scraped_pages_updated_at
    BEFORE UPDATE ON scraped_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE scraped_pages IS
    'One row per crawled page. Stores raw HTML/text and LLM-generated markdown. '
    'Links back to the skill_call that produced it; onboarding_id / user_id / message_id are optional.';

