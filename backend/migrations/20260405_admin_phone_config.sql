-- Migration: Add admin phone number config entries
-- Description: Allow phone numbers to be used for admin/super admin access
-- Applied on: 2026-04-05

-- Add phone number allowlist config entries
INSERT INTO system_config (key, value, description)
VALUES
    ('auth.super_admin_phones', '[]', 'JSON array of super admin phone numbers (10 digits). Only these phones may access admin UI and admin management APIs.'),
    ('auth.admin_phones', '[]', 'JSON array of admin phone numbers (10 digits). (Admin UI features can optionally use this.)')
ON CONFLICT (key) DO NOTHING;

