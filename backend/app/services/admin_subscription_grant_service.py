"""
Admin Subscription Grants: Allow admins to grant full subscription access to team members.
Tracks audit log of who granted/revoked access.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.sql_builder import build_query

logger = structlog.get_logger()
admin_subscription_grants_t = Table("admin_subscription_grants")
admin_subscription_grant_logs_t = Table("admin_subscription_grant_logs")
users_t = Table("users")
u_target_t = users_t.as_("u_target")
u_granted_by_t = users_t.as_("u_granted_by")
u_revoked_by_t = users_t.as_("u_revoked_by")
u_admin_t = users_t.as_("u_admin")
asg_search_t = admin_subscription_grants_t.as_("asg_search")


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
        has_grant_q = build_query(
            PostgreSQLQuery.from_(admin_subscription_grants_t)
            .select(admin_subscription_grants_t.id)
            .where(admin_subscription_grants_t.user_id == Parameter("%s"))
            .where(admin_subscription_grants_t.is_active.isin([True]))
            .limit(1),
            [uid],
        )
        row = await conn.fetchrow(has_grant_q.sql, *has_grant_q.params)
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
        grant_details_q = build_query(
            PostgreSQLQuery.from_(admin_subscription_grants_t)
            .left_join(u_granted_by_t)
            .on(u_granted_by_t.id == admin_subscription_grants_t.granted_by_user_id)
            .select(
                admin_subscription_grants_t.id,
                admin_subscription_grants_t.user_id,
                admin_subscription_grants_t.granted_by_user_id,
                admin_subscription_grants_t.reason,
                admin_subscription_grants_t.is_active,
                admin_subscription_grants_t.granted_at,
                u_granted_by_t.email.as_("granted_by_email"),
            )
            .where(admin_subscription_grants_t.user_id == Parameter("%s"))
            .where(admin_subscription_grants_t.is_active.isin([True]))
            .limit(1),
            [uid],
        )
        row = await conn.fetchrow(grant_details_q.sql, *grant_details_q.params)

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
        target_user_q = build_query(
            PostgreSQLQuery.from_(users_t)
            .select(users_t.id, users_t.email, users_t.phone_number)
            .where(users_t.id == Parameter("%s")),
            [target_uid],
        )
        user_row = await conn.fetchrow(target_user_q.sql, *target_user_q.params)
        if not user_row:
            return {"success": False, "error": "Target user not found"}

        grant_upsert_q = build_query(
            PostgreSQLQuery.into(admin_subscription_grants_t)
            .columns(
                admin_subscription_grants_t.user_id,
                admin_subscription_grants_t.granted_by_user_id,
                admin_subscription_grants_t.reason,
                admin_subscription_grants_t.is_active,
                admin_subscription_grants_t.granted_at,
                admin_subscription_grants_t.revoked_at,
                admin_subscription_grants_t.revoked_by_user_id,
            )
            .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), True, fn.Now(), None, None)
            .on_conflict(admin_subscription_grants_t.user_id)
            .do_update(admin_subscription_grants_t.granted_by_user_id)
            .do_update(admin_subscription_grants_t.reason)
            .do_update(admin_subscription_grants_t.is_active)
            .do_update(admin_subscription_grants_t.granted_at)
            .do_update(admin_subscription_grants_t.revoked_at)
            .do_update(admin_subscription_grants_t.revoked_by_user_id),
            [target_uid, admin_uid, reason_text],
        )
        await conn.execute(grant_upsert_q.sql, *grant_upsert_q.params)

        # Log the action
        insert_grant_log_q = build_query(
            PostgreSQLQuery.into(admin_subscription_grant_logs_t)
            .columns(
                admin_subscription_grant_logs_t.target_user_id,
                admin_subscription_grant_logs_t.action,
                admin_subscription_grant_logs_t.admin_user_id,
                admin_subscription_grant_logs_t.reason,
            )
            .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s")),
            [target_uid, "grant", admin_uid, reason_text],
        )
        await conn.execute(insert_grant_log_q.sql, *insert_grant_log_q.params)

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
        active_grant_q = build_query(
            PostgreSQLQuery.from_(admin_subscription_grants_t)
            .select(admin_subscription_grants_t.id)
            .where(admin_subscription_grants_t.user_id == Parameter("%s"))
            .where(admin_subscription_grants_t.is_active.isin([True])),
            [target_uid],
        )
        grant_row = await conn.fetchrow(active_grant_q.sql, *active_grant_q.params)
        if not grant_row:
            return {"success": False, "error": "No active subscription grant found for this user"}

        # Revoke the grant
        revoke_grant_q = build_query(
            PostgreSQLQuery.update(admin_subscription_grants_t)
            .set(admin_subscription_grants_t.is_active, False)
            .set(admin_subscription_grants_t.revoked_at, fn.Now())
            .set(admin_subscription_grants_t.revoked_by_user_id, Parameter("%s"))
            .where(admin_subscription_grants_t.user_id == Parameter("%s")),
            [admin_uid, target_uid],
        )
        await conn.execute(revoke_grant_q.sql, *revoke_grant_q.params)

        # Log the action
        insert_revoke_log_q = build_query(
            PostgreSQLQuery.into(admin_subscription_grant_logs_t)
            .columns(
                admin_subscription_grant_logs_t.target_user_id,
                admin_subscription_grant_logs_t.action,
                admin_subscription_grant_logs_t.admin_user_id,
                admin_subscription_grant_logs_t.reason,
            )
            .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s")),
            [target_uid, "revoke", admin_uid, reason_text],
        )
        await conn.execute(insert_revoke_log_q.sql, *insert_revoke_log_q.params)

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
        list_grants_q = build_query(
            PostgreSQLQuery.from_(admin_subscription_grants_t)
            .join(u_target_t)
            .on(u_target_t.id == admin_subscription_grants_t.user_id)
            .left_join(u_granted_by_t)
            .on(u_granted_by_t.id == admin_subscription_grants_t.granted_by_user_id)
            .left_join(u_revoked_by_t)
            .on(u_revoked_by_t.id == admin_subscription_grants_t.revoked_by_user_id)
            .select(
                admin_subscription_grants_t.id,
                admin_subscription_grants_t.user_id,
                admin_subscription_grants_t.granted_by_user_id,
                admin_subscription_grants_t.reason,
                admin_subscription_grants_t.is_active,
                admin_subscription_grants_t.granted_at,
                admin_subscription_grants_t.revoked_at,
                admin_subscription_grants_t.revoked_by_user_id,
                u_target_t.email.as_("user_email"),
                u_target_t.phone_number.as_("user_phone"),
                u_granted_by_t.email.as_("granted_by_email"),
                u_revoked_by_t.email.as_("revoked_by_email"),
            )
            .orderby(admin_subscription_grants_t.granted_at, order=Order.desc)
        )
        rows = await conn.fetch(list_grants_q.sql, *list_grants_q.params)

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
        base_audit_q = (
            PostgreSQLQuery.from_(admin_subscription_grant_logs_t)
            .join(u_target_t)
            .on(u_target_t.id == admin_subscription_grant_logs_t.target_user_id)
            .left_join(u_admin_t)
            .on(u_admin_t.id == admin_subscription_grant_logs_t.admin_user_id)
            .select(
                admin_subscription_grant_logs_t.id,
                admin_subscription_grant_logs_t.target_user_id,
                admin_subscription_grant_logs_t.action,
                admin_subscription_grant_logs_t.admin_user_id,
                admin_subscription_grant_logs_t.reason,
                admin_subscription_grant_logs_t.created_at,
                u_target_t.email.as_("target_email"),
                u_admin_t.email.as_("admin_email"),
            )
        )
        if target_user_id:
            target_uid = _as_uuid(target_user_id)
            audit_for_target_q = build_query(
                base_audit_q.where(admin_subscription_grant_logs_t.target_user_id == Parameter("%s"))
                .orderby(admin_subscription_grant_logs_t.created_at, order=Order.desc)
                .limit(100),
                [target_uid],
            )
            rows = await conn.fetch(audit_for_target_q.sql, *audit_for_target_q.params)
        else:
            audit_all_q = build_query(
                base_audit_q.orderby(admin_subscription_grant_logs_t.created_at, order=Order.desc).limit(100)
            )
            rows = await conn.fetch(audit_all_q.sql, *audit_all_q.params)

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
        search_users_q = build_query(
            PostgreSQLQuery.from_(users_t)
            .left_join(asg_search_t)
            .on((asg_search_t.user_id == users_t.id) & (asg_search_t.is_active.isin([True])))
            .select(
                users_t.id,
                users_t.email,
                users_t.phone_number,
                users_t.created_at,
                asg_search_t.id.as_("active_grant_id"),
            )
            .where((users_t.email.ilike(Parameter("%s"))) | (users_t.phone_number.ilike(Parameter("%s"))))
            .orderby(users_t.created_at, order=Order.desc)
            .limit(20),
            [f"%{q}%", f"%{q}%"],
        )
        rows = await conn.fetch(search_users_q.sql, *search_users_q.params)

    users = []
    for r in rows:
        users.append({
            "id": str(r["id"]),
            "email": r["email"] or "",
            "phone_number": r["phone_number"] or "",
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "has_admin_grant": r.get("active_grant_id") is not None,
        })

    return users

