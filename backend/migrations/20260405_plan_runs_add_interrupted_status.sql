-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration: Add 'interrupted' status to plan_runs
-- Date: 2026-04-05
-- Description: Add 'interrupted' status to plan_runs_status_check constraint
--              for handling backend restart scenarios.
-- ═══════════════════════════════════════════════════════════════════════════════

-- Drop the existing check constraint and recreate with the new status value
ALTER TABLE plan_runs DROP CONSTRAINT IF EXISTS plan_runs_status_check;

ALTER TABLE plan_runs ADD CONSTRAINT plan_runs_status_check
    CHECK (status IN ('draft', 'approved', 'running', 'executing', 'done', 'error', 'cancelled', 'interrupted'));

