-- Migration: Add error_message column to plan_runs
-- Description: Stores human-readable error detail when a plan fails or is interrupted.

ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS error_message TEXT;
