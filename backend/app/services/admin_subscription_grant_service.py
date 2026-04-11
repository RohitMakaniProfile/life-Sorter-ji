"""
Admin Subscription Grants: Allow admins to grant full subscription access to team members.
Tracks audit log of who granted/revoked access.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from app.db import get_pool
from app.repositories import admin_grants_repository as grants_repo
from app.repositories import users_repository as users_repo

logger = structlog.get_logger()


def _as_uuid(user_id: str) -> UUID:
    return UUID(str(user_id).strip())


async def has_admin_subscription_grant(user_id: str) -> bool:
    if not user_id or not user_id.strip():
        return False
    pool = get_pool()
    async with pool.acquire() as conn:
        return await grants_repo.has_active_grant(conn, _as_uuid(user_id))


async def get_admin_subscription_grant(user_id: str) -> Optional[dict[str, Any]]:
    if not user_id or not user_id.strip():
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await grants_repo.find_active_with_granter(conn, _as_uuid(user_id))
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
    *, target_user_id: str, admin_user_id: str, reason: str = "",
) -> dict[str, Any]:
    target_uid = _as_uuid(target_user_id)
    admin_uid = _as_uuid(admin_user_id)
    reason_text = (reason or "").strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        user_row = await users_repo.find_by_id(conn, target_uid)
        if not user_row:
            return {"success": False, "error": "Target user not found"}
        await grants_repo.upsert_grant(conn, target_uid, admin_uid, reason_text)
        await grants_repo.insert_log(conn, target_uid, "grant", admin_uid, reason_text)

    logger.info("Admin subscription grant created", target_user_id=target_user_id,
                admin_user_id=admin_user_id, reason=reason_text)
    return {
        "success": True,
        "user_id": target_user_id,
        "user_email": user_row["email"] or "",
        "user_phone": user_row["phone_number"] or "",
    }


async def revoke_subscription(
    *, target_user_id: str, admin_user_id: str, reason: str = "",
) -> dict[str, Any]:
    target_uid = _as_uuid(target_user_id)
    admin_uid = _as_uuid(admin_user_id)
    reason_text = (reason or "").strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        grant_row = await grants_repo.find_active_grant_id(conn, target_uid)
        if not grant_row:
            return {"success": False, "error": "No active subscription grant found for this user"}
        await grants_repo.revoke_grant(conn, target_uid, admin_uid)
        await grants_repo.insert_log(conn, target_uid, "revoke", admin_uid, reason_text)

    logger.info("Admin subscription grant revoked", target_user_id=target_user_id,
                admin_user_id=admin_user_id, reason=reason_text)
    return {"success": True, "user_id": target_user_id}


async def list_all_grants() -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await grants_repo.find_all_with_user_details(conn)
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
    from uuid import UUID as _UUID
    pool = get_pool()
    uid = _as_uuid(target_user_id) if target_user_id else None
    async with pool.acquire() as conn:
        rows = await grants_repo.find_audit_log(conn, uid)
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
    q = (query or "").strip()
    if not q or len(q) < 2:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await users_repo.search_for_grant(conn, q)
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