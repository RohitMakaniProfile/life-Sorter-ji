-- Optional onboarding fields useful for replay/debugging and lifecycle tracking.
-- Idempotent; safe to re-run.

-- Unified Q&A log (optional): array of {question, answer, question_type, timestamp}
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS questions_answers JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Onboarding lifecycle timestamp (optional)
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;

-- Optional pointer to crawl cache (if you want a stable cache key rather than crawl_run_id)
ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS crawl_cache_key TEXT;

