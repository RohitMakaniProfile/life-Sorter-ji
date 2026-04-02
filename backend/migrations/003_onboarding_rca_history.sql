-- Add dynamic RCA question/answer storage to the onboarding table.
-- Stored as JSONB so the number of questions can grow over time.

ALTER TABLE onboarding
ADD COLUMN IF NOT EXISTS rca_qa JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Optional convenience index for searching by session_id is already present.

