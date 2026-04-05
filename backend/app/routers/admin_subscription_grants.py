"""
═══════════════════════════════════════════════════════════════
ADMIN SUBSCRIPTION GRANTS ROUTER
═══════════════════════════════════════════════════════════════
Allows super admins to grant/revoke full subscription access to team members.
All actions are logged with the admin's user ID for audit purposes.

GET    /api/v1/admin/subscription-grants              — list all grants
GET    /api/v1/admin/subscription-grants/audit-log    — get audit log
GET    /api/v1/admin/subscription-grants/search-users — search users by email/phone
POST   /api/v1/admin/subscription-grants/grant        — grant subscription to user
POST   /api/v1/admin/subscription-grants/revoke       — revoke subscription from user
"""

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.middleware.auth_context import require_request_user, require_super_admin
from app.middleware.rate_limit import limiter
from app.services import admin_subscription_grant_service

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/subscription-grants", tags=["Admin-Subscription-Grants"])


class GrantRequest(BaseModel):
    user_id: str = Field(..., description="Target user ID (UUID) to grant subscription to")
    reason: str = Field("", description="Optional reason for granting subscription (e.g., 'Team member', 'Testing')")


class RevokeRequest(BaseModel):
    user_id: str = Field(..., description="Target user ID (UUID) to revoke subscription from")
    reason: str = Field("", description="Optional reason for revoking subscription")


class GrantEntry(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_phone: str
    granted_by_user_id: Optional[str]
    granted_by_email: str
    reason: str
    is_active: bool
    granted_at: Optional[str]
    revoked_at: Optional[str]
    revoked_by_user_id: Optional[str]
    revoked_by_email: str


class AuditLogEntry(BaseModel):
    id: str
    target_user_id: str
    target_email: str
    action: str
    admin_user_id: Optional[str]
    admin_email: str
    reason: str
    created_at: Optional[str]


class UserSearchResult(BaseModel):
    id: str
    email: str
    phone_number: str
    created_at: Optional[str]
    has_admin_grant: bool


@router.get("", response_model=dict[str, Any])
@limiter.limit("30/minute")
async def list_grants(request: Request):
    """
    List all admin subscription grants (active and inactive).
    Requires super admin access.
    """
    require_super_admin(request)
    grants = await admin_subscription_grant_service.list_all_grants()
    return {"grants": grants}


@router.get("/audit-log", response_model=dict[str, Any])
@limiter.limit("30/minute")
async def get_audit_log(
    request: Request,
    user_id: Optional[str] = Query(None, description="Optional: filter by target user ID"),
):
    """
    Get audit log of all grant/revoke actions.
    Requires super admin access.
    """
    require_super_admin(request)
    logs = await admin_subscription_grant_service.get_grant_audit_log(user_id)
    return {"logs": logs}


@router.get("/search-users", response_model=dict[str, Any])
@limiter.limit("60/minute")
async def search_users(
    request: Request,
    q: str = Query(..., description="Search query (email or phone, min 2 chars)"),
):
    """
    Search users by email or phone number for the admin grant UI.
    Requires super admin access.
    """
    require_super_admin(request)
    users = await admin_subscription_grant_service.search_users(q)
    return {"users": users}


@router.post("/grant", response_model=dict[str, Any])
@limiter.limit("20/minute")
async def grant_subscription(request: Request, body: GrantRequest = Body(...)):
    """
    Grant full subscription access to a user.
    The admin's user ID is logged for audit purposes.
    Requires super admin access.
    """
    require_super_admin(request)
    admin_user = require_request_user(request)
    admin_uid = str(admin_user.get("id") or "").strip()

    if not admin_uid:
        raise HTTPException(status_code=401, detail="Admin user ID required")

    target_uid = (body.user_id or "").strip()
    if not target_uid:
        raise HTTPException(status_code=400, detail="user_id is required")

    result = await admin_subscription_grant_service.grant_subscription(
        target_user_id=target_uid,
        admin_user_id=admin_uid,
        reason=body.reason,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to grant subscription"))

    logger.info(
        "Admin granted subscription",
        admin_user_id=admin_uid,
        admin_email=admin_user.get("email"),
        target_user_id=target_uid,
        target_email=result.get("user_email"),
        reason=body.reason,
    )

    return result


@router.post("/revoke", response_model=dict[str, Any])
@limiter.limit("20/minute")
async def revoke_subscription(request: Request, body: RevokeRequest = Body(...)):
    """
    Revoke admin-granted subscription from a user.
    The admin's user ID is logged for audit purposes.
    Requires super admin access.
    """
    require_super_admin(request)
    admin_user = require_request_user(request)
    admin_uid = str(admin_user.get("id") or "").strip()

    if not admin_uid:
        raise HTTPException(status_code=401, detail="Admin user ID required")

    target_uid = (body.user_id or "").strip()
    if not target_uid:
        raise HTTPException(status_code=400, detail="user_id is required")

    result = await admin_subscription_grant_service.revoke_subscription(
        target_user_id=target_uid,
        admin_user_id=admin_uid,
        reason=body.reason,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to revoke subscription"))

    logger.info(
        "Admin revoked subscription",
        admin_user_id=admin_uid,
        admin_email=admin_user.get("email"),
        target_user_id=target_uid,
        reason=body.reason,
    )

    return result

