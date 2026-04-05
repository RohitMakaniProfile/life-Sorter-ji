-- Migration: Add admin_subscription_grants tables
-- Description: Allow admins to grant full subscription access to team members with audit logging.
-- Applied on: 2026-04-05

-- ── Admin Subscription Grants ──────────────────────────────────────────────────
-- Allows admins to grant full subscription access to team members.
-- Tracks who granted access (for audit purposes).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_subscription_grants (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granted_by_user_id      UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    reason                  TEXT NOT NULL DEFAULT '',
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    granted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at              TIMESTAMPTZ NULL,
    revoked_by_user_id      UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT admin_subscription_grants_user_unique UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grants_user
    ON admin_subscription_grants (user_id);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grants_granted_by
    ON admin_subscription_grants (granted_by_user_id);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grants_active
    ON admin_subscription_grants (is_active) WHERE is_active = TRUE;

COMMENT ON TABLE admin_subscription_grants IS
    'Admin-granted full subscription access for team members. Tracks audit trail of who granted/revoked access.';

-- Audit log for admin subscription grant actions
CREATE TABLE IF NOT EXISTS admin_subscription_grant_logs (
    id                      BIGSERIAL PRIMARY KEY,
    target_user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action                  TEXT NOT NULL CHECK (action IN ('grant', 'revoke')),
    admin_user_id           UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    reason                  TEXT NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grant_logs_target
    ON admin_subscription_grant_logs (target_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_subscription_grant_logs_admin
    ON admin_subscription_grant_logs (admin_user_id, created_at DESC);

COMMENT ON TABLE admin_subscription_grant_logs IS
    'Audit log for all admin subscription grant/revoke actions.';

