-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration: Fix NULL agent_id values in conversations
-- Date: 2026-04-05
-- Description: Fix any conversations with NULL agent_id by assigning them to
--              the default agent (research-orchestrator).
-- ═══════════════════════════════════════════════════════════════════════════════

-- Fix existing NULL agent_id values
UPDATE conversations
SET agent_id = 'research-orchestrator', updated_at = NOW()
WHERE agent_id IS NULL;

-- Ensure the constraint is still in place
-- Note: This will fail if there are still NULL values or orphaned agent_ids
-- The update above should have fixed all NULL values.

