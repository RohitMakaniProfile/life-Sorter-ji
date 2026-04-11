"""
Plan purchases: checkout context (order → plan), grants per authenticated user (JWT `sub` / users.id).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional, Tuple
from uuid import UUID

import asyncpg
import structlog

from app.db import get_pool
from app.services import juspay_service
from app.services import admin_subscription_grant_service
from app.repositories import plans_repository as plans_repo
from app.repositories import user_plan_grants_repository as grants_repo
from app.repositories import payment_checkout_repository as checkout_repo

logger = structlog.get_logger()

CAPABILITY_KEYS = ("deep_analysis_report", "execute_report_actions")

# Agents listed here require the user to have an active plan grant with the specified capability.
AGENT_REQUIRED_CAPABILITY: dict[str, str] = {
    "research-orchestrator": "deep_analysis_report",
}


def _as_uuid(user_id: str) -> UUID:
    return UUID(str(user_id).strip())


def _feature_truthy(features: Any, key: str) -> bool:
    if not isinstance(features, dict):
        return False
    v = features.get(key)
    return v is True or v == "true"


def _normalize_features(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


async def check_agent_access(*, user_id: str, agent_id: str) -> dict[str, Any]:
    required_cap = AGENT_REQUIRED_CAPABILITY.get(agent_id)
    if not required_cap:
        return {"allowed": True}
    if not user_id or not user_id.strip():
        return {"allowed": False, "reason": "Authentication required to use this agent.",
                "required_capability": required_cap}

    if await admin_subscription_grant_service.has_admin_subscription_grant(user_id):
        return {"allowed": True, "via_admin_grant": True}

    uid = _as_uuid(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await grants_repo.find_by_user_with_plan(conn, uid)

    if not rows:
        plan_info = await _find_plan_for_capability(required_cap)
        return {"allowed": False, "reason": "A paid plan is required to use this agent.",
                "required_capability": required_cap, **plan_info}

    for r in rows:
        features = _normalize_features(r.get("features"))
        if _feature_truthy(features, required_cap):
            cr = r.get("credits_remaining")
            if cr is None or cr > 0:
                return {"allowed": True, "plan_slug": r["plan_slug"], "plan_name": r["plan_name"]}

    plan_info = await _find_plan_for_capability(required_cap)
    return {"allowed": False, "reason": "Your current plan does not include access to this agent.",
            "required_capability": required_cap, **plan_info}


async def _find_plan_for_capability(capability: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await plans_repo.find_all_active(conn)
    for r in rows:
        row_dict = dict(r)
        feats = _normalize_features(row_dict.get("features", {}))
        if _feature_truthy(feats, capability):
            price = row_dict.get("price_inr")
            if isinstance(price, Decimal):
                price = float(price)
            return {
                "required_plan_slug": row_dict["slug"],
                "required_plan_name": row_dict["name"],
                "required_plan_price": price,
            }
    return {}


async def save_checkout_context(*, order_id: str, user_id: str, plan_id: str) -> None:
    uid = _as_uuid(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        await checkout_repo.upsert(conn, order_id.strip(), uid, plan_id)


async def complete_plan_purchase(*, user_id: str, order_id: str) -> Tuple[bool, Optional[str]]:
    uid = _as_uuid(user_id)
    oid = order_id.strip()
    if not oid:
        return False, "order_id is required"

    pool = get_pool()
    async with pool.acquire() as conn:
        ctx = await checkout_repo.find_by_order_and_user(conn, oid, uid)
        existing = await grants_repo.find_by_order_id(conn, oid)

        if existing:
            if existing["user_id"] != uid:
                return False, "This payment was already applied to another account."
            await checkout_repo.delete_by_order_id(conn, oid)
            return True, None

        if not ctx:
            return False, "No pending checkout for this order. Start checkout again while signed in."

        plan_row = await plans_repo.find_active_by_id(conn, ctx["plan_id"])
        if not plan_row:
            return False, "Plan is no longer available."

    price_inr = plan_row["price_inr"]
    min_amt = float(price_inr) if isinstance(price_inr, Decimal) else float(price_inr)

    verification = await juspay_service.verify_charged_order(oid, min_amt)
    if not verification.get("verified"):
        return False, verification.get("reason") or "Payment could not be verified"

    credits_alloc = plan_row["credits_allocation"]

    try:
        async with pool.acquire() as conn:
            await grants_repo.insert(conn, uid, str(plan_row["id"]), oid, credits_alloc)
            await checkout_repo.delete_by_order_id(conn, oid)
    except asyncpg.exceptions.UniqueViolationError:
        async with pool.acquire() as conn2:
            g = await grants_repo.find_owner_by_order_id(conn2, oid)
        if g and g["user_id"] == uid:
            return True, None
        return False, "This payment was already applied."

    return True, None


def _aggregate_capability(rows: list[dict[str, Any]], cap_key: str) -> dict[str, Any]:
    matching = [r for r in rows if _feature_truthy(_normalize_features(r.get("features")), cap_key)]
    if not matching:
        return {"allowed": False, "unlimited": False, "credits_remaining": 0}
    if any(r.get("credits_remaining") is None for r in matching):
        return {"allowed": True, "unlimited": True, "credits_remaining": None}
    total = sum(int(r["credits_remaining"] or 0) for r in matching)
    return {"allowed": total > 0, "unlimited": False, "credits_remaining": total}


async def get_user_entitlements(*, user_id: str) -> dict[str, Any]:
    uid = _as_uuid(user_id)
    admin_grant = await admin_subscription_grant_service.get_admin_subscription_grant(user_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await grants_repo.find_entitlements_by_user(conn, uid)

    grant_rows: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        ga = d.get("granted_at")
        if ga is not None and hasattr(ga, "isoformat"):
            d["granted_at"] = ga.isoformat()
        pr = d.get("price_inr")
        if isinstance(pr, Decimal):
            d["price_inr"] = float(pr)
        d["features"] = _normalize_features(d.get("features"))
        grant_rows.append(d)

    grants_out: list[dict[str, Any]] = []
    if admin_grant:
        grants_out.append({
            "plan_slug": "admin_granted",
            "plan_name": "Admin Granted Full Access",
            "order_id": f"admin_grant:{admin_grant['id']}",
            "credits_remaining": None,
            "credits_unlimited": True,
            "granted_at": admin_grant.get("granted_at"),
            "granted_by_email": admin_grant.get("granted_by_email", ""),
            "is_admin_grant": True,
            "features": {key: True for key in CAPABILITY_KEYS},
        })
    for g in grant_rows:
        cr = g.get("credits_remaining")
        grants_out.append({
            "plan_slug": g["plan_slug"],
            "plan_name": g["plan_name"],
            "order_id": g["order_id"],
            "credits_remaining": cr,
            "credits_unlimited": cr is None,
            "granted_at": g.get("granted_at"),
            "features": g.get("features") or {},
        })

    capabilities: dict[str, Any] = {}
    if admin_grant:
        for key in CAPABILITY_KEYS:
            capabilities[key] = {"allowed": True, "unlimited": True, "credits_remaining": None, "via_admin_grant": True}
    else:
        for key in CAPABILITY_KEYS:
            capabilities[key] = _aggregate_capability(grant_rows, key)

    return {
        "user_id": str(user_id).strip(),
        "grants": grants_out,
        "capabilities": capabilities,
        "has_admin_grant": admin_grant is not None,
        "admin_grant": admin_grant,
    }