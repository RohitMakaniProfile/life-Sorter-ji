"""
Admin Subscription Grants: Allow admins to grant full subscription access to team members.
Tracks audit log of who granted/revoked access.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from app.db import get_pool

logger = structlog.get_logger()


def _as_uuid(user_id: str) -> UUID:
    return UUID(str(user_id).strip())


async def has_admin_subscription_grant(user_id: str) -> bool:
    """
    Check if a user has an active admin-granted subscription.
    """
    if not user_id or not user_id.strip():
        return False

    uid = _as_uuid(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM admin_subscription_grants
            WHERE user_id = $1 AND is_active = TRUE
            LIMIT 1
            """,
            uid,
        )
    return row is not None


async def get_admin_subscription_grant(user_id: str) -> Optional[dict[str, Any]]:
    """
    Get admin subscription grant details for a user.
    Returns None if no active grant exists.
    """
    if not user_id or not user_id.strip():
        return None

    uid = _as_uuid(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                asg.id,
                asg.user_id,
                asg.granted_by_user_id,
                asg.reason,
                asg.is_active,
                asg.granted_at,
                u_granted_by.email AS granted_by_email
            FROM admin_subscription_grants asg
            LEFT JOIN users u_granted_by ON u_granted_by.id = asg.granted_by_user_id
            WHERE asg.user_id = $1 AND asg.is_active = TRUE
            LIMIT 1
            """,
            uid,
        )

    if not row:
        return None

    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "granted_by_user_id": str(row["granted_by_user_id"]),
        "granted_by_email": row["granted_by_email"] or "",
        "reason": row["reason"] or "",
        "is_active": row["is_active"],
        "granted_at": row["granted_at"].isoformat() if row["granted_at"] else None,
    }


async def grant_subscription(
    *,
    target_user_id: str,
    admin_user_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """
    Grant full subscription access to a user. If already granted, update the reason.
    Logs the action for audit purposes.
    """
    target_uid = _as_uuid(target_user_id)
    admin_uid = _as_uuid(admin_user_id)
    reason_text = (reason or "").strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check if target user exists
        user_row = await conn.fetchrow(
            "SELECT id, email, phone_number FROM users WHERE id = $1",
            target_uid,
        )
        if not user_row:
            return {"success": False, "error": "Target user not found"}

        # Upsert the grant
        await conn.execute(
            """
            INSERT INTO admin_subscription_grants (user_id, granted_by_user_id, reason, is_active, granted_at)
            VALUES ($1, $2, $3, TRUE, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                granted_by_user_id = EXCLUDED.granted_by_user_id,
                reason = EXCLUDED.reason,
                is_active = TRUE,
                granted_at = NOW(),
                revoked_at = NULL,
                revoked_by_user_id = NULL
            """,
            target_uid,
            admin_uid,
            reason_text,
        )

        # Log the action
        await conn.execute(
            """
            INSERT INTO admin_subscription_grant_logs (target_user_id, action, admin_user_id, reason)
            VALUES ($1, 'grant', $2, $3)
            """,
            target_uid,
            admin_uid,
            reason_text,
        )

    logger.info(
        "Admin subscription grant created",
        target_user_id=target_user_id,
        admin_user_id=admin_user_id,
        reason=reason_text,
    )

    return {
        "success": True,
        "user_id": target_user_id,
        "user_email": user_row["email"] or "",
        "user_phone": user_row["phone_number"] or "",
    }


async def revoke_subscription(
    *,
    target_user_id: str,
    admin_user_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """
    Revoke admin-granted subscription access from a user.
    Logs the action for audit purposes.
    """
    target_uid = _as_uuid(target_user_id)
    admin_uid = _as_uuid(admin_user_id)
    reason_text = (reason or "").strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check if grant exists
        grant_row = await conn.fetchrow(
            "SELECT id FROM admin_subscription_grants WHERE user_id = $1 AND is_active = TRUE",
            target_uid,
        )
        if not grant_row:
            return {"success": False, "error": "No active subscription grant found for this user"}

        # Revoke the grant
        await conn.execute(
            """
            UPDATE admin_subscription_grants
            SET is_active = FALSE, revoked_at = NOW(), revoked_by_user_id = $2
            WHERE user_id = $1
            """,
            target_uid,
            admin_uid,
        )

        # Log the action
        await conn.execute(
            """
            INSERT INTO admin_subscription_grant_logs (target_user_id, action, admin_user_id, reason)
            VALUES ($1, 'revoke', $2, $3)
            """,
            target_uid,
            admin_uid,
            reason_text,
        )

    logger.info(
        "Admin subscription grant revoked",
        target_user_id=target_user_id,
        admin_user_id=admin_user_id,
        reason=reason_text,
    )

    return {"success": True, "user_id": target_user_id}


async def list_all_grants() -> list[dict[str, Any]]:
    """
    List all admin subscription grants (active and inactive) with user details.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                asg.id,
                asg.user_id,
                asg.granted_by_user_id,
                asg.reason,
                asg.is_active,
                asg.granted_at,
                asg.revoked_at,
                asg.revoked_by_user_id,
                u_target.email AS user_email,
                u_target.phone_number AS user_phone,
                u_granted_by.email AS granted_by_email,
                u_revoked_by.email AS revoked_by_email
            FROM admin_subscription_grants asg
            JOIN users u_target ON u_target.id = asg.user_id
            LEFT JOIN users u_granted_by ON u_granted_by.id = asg.granted_by_user_id
            LEFT JOIN users u_revoked_by ON u_revoked_by.id = asg.revoked_by_user_id
            ORDER BY asg.granted_at DESC
            """
        )

    grants = []
    for r in rows:
        grants.append({
            "id": str(r["id"]),
            "user_id": str(r["user_id"]),
            "user_email": r["user_email"] or "",
            "user_phone": r["user_phone"] or "",
            "granted_by_user_id": str(r["granted_by_user_id"]) if r["granted_by_user_id"] else None,
            "granted_by_email": r["granted_by_email"] or "",
            "reason": r["reason"] or "",
            "is_active": r["is_active"],
            "granted_at": r["granted_at"].isoformat() if r["granted_at"] else None,
            "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
            "revoked_by_user_id": str(r["revoked_by_user_id"]) if r["revoked_by_user_id"] else None,
            "revoked_by_email": r["revoked_by_email"] or "",
        })

    return grants


async def get_grant_audit_log(target_user_id: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Get audit log of all grant/revoke actions, optionally filtered by target user.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if target_user_id:
            target_uid = _as_uuid(target_user_id)
            rows = await conn.fetch(
                """
                SELECT
                    agl.id,
                    agl.target_user_id,
                    agl.action,
                    agl.admin_user_id,
                    agl.reason,
                    agl.created_at,
                    u_target.email AS target_email,
                    u_admin.email AS admin_email
                FROM admin_subscription_grant_logs agl
                JOIN users u_target ON u_target.id = agl.target_user_id
                LEFT JOIN users u_admin ON u_admin.id = agl.admin_user_id
                WHERE agl.target_user_id = $1
                ORDER BY agl.created_at DESC
                LIMIT 100
                """,
                target_uid,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT
                    agl.id,
                    agl.target_user_id,
                    agl.action,
                    agl.admin_user_id,
                    agl.reason,
                    agl.created_at,
                    u_target.email AS target_email,
                    u_admin.email AS admin_email
                FROM admin_subscription_grant_logs agl
                JOIN users u_target ON u_target.id = agl.target_user_id
                LEFT JOIN users u_admin ON u_admin.id = agl.admin_user_id
                ORDER BY agl.created_at DESC
                LIMIT 100
                """
            )

    logs = []
    for r in rows:
        logs.append({
            "id": str(r["id"]),
            "target_user_id": str(r["target_user_id"]),
            "target_email": r["target_email"] or "",
            "action": r["action"],
            "admin_user_id": str(r["admin_user_id"]) if r["admin_user_id"] else None,
            "admin_email": r["admin_email"] or "",
            "reason": r["reason"] or "",
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    return logs


async def search_users(query: str) -> list[dict[str, Any]]:
    """
    Search users by email or phone for admin grant UI.
    """
    q = (query or "").strip()
    if not q or len(q) < 2:
        return []

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.id,
                u.email,
                u.phone_number,
                u.created_at,
                (SELECT 1 FROM admin_subscription_grants asg WHERE asg.user_id = u.id AND asg.is_active = TRUE LIMIT 1) IS NOT NULL AS has_admin_grant
            FROM users u
            WHERE
                u.email ILIKE $1 OR u.phone_number ILIKE $1
            ORDER BY u.created_at DESC
            LIMIT 20
            """,
            f"%{q}%",
        )

    users = []
    for r in rows:
        users.append({
            "id": str(r["id"]),
            "email": r["email"] or "",
            "phone_number": r["phone_number"] or "",
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "has_admin_grant": bool(r["has_admin_grant"]),
        })

    return users

