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

logger = structlog.get_logger()

CAPABILITY_KEYS = ("deep_analysis_report", "execute_report_actions")

# ── Agent → required capability mapping ──────────────────────────────────────
# Agents listed here require the user to have an active plan grant whose
# `features` JSONB includes the specified capability key set to true.
# Agents NOT listed here are free / unrestricted.
AGENT_REQUIRED_CAPABILITY: dict[str, str] = {
    "research-orchestrator": "deep_analysis_report",
}


async def check_agent_access(*, user_id: str, agent_id: str) -> dict[str, Any]:
    """
    Check whether a user may use a given agent.

    Returns {"allowed": True} or {"allowed": False, "reason": "...", "required_plan_slug": "..."}.
    """
    required_cap = AGENT_REQUIRED_CAPABILITY.get(agent_id)
    if not required_cap:
        return {"allowed": True}

    if not user_id or not user_id.strip():
        return {
            "allowed": False,
            "reason": "Authentication required to use this agent.",
            "required_capability": required_cap,
        }

    # Check if user has admin-granted subscription (full access)
    if await admin_subscription_grant_service.has_admin_subscription_grant(user_id):
        return {"allowed": True, "via_admin_grant": True}

    uid = _as_uuid(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT g.id, p.slug AS plan_slug, p.name AS plan_name, g.credits_remaining, p.features
            FROM user_plan_grants g
            JOIN plans p ON p.id = g.plan_id AND p.active = TRUE
            WHERE g.user_id = $1
            ORDER BY g.granted_at DESC
            """,
            uid,
        )

    if not rows:
        # No grants at all — find which plan they need
        plan_info = await _find_plan_for_capability(required_cap)
        return {
            "allowed": False,
            "reason": "A paid plan is required to use this agent.",
            "required_capability": required_cap,
            **plan_info,
        }


    for r in rows:
        features = _normalize_features(r.get("features"))
        if _feature_truthy(features, required_cap):
            cr = r.get("credits_remaining")
            # credits_remaining NULL = unlimited; > 0 = still has credits
            if cr is None or cr > 0:
                return {"allowed": True, "plan_slug": r["plan_slug"], "plan_name": r["plan_name"]}

    # Has grants but none with the right capability
    plan_info = await _find_plan_for_capability(required_cap)
    return {
        "allowed": False,
        "reason": "Your current plan does not include access to this agent.",
        "required_capability": required_cap,
        **plan_info,
    }


async def _find_plan_for_capability(capability: str) -> dict[str, Any]:
    """Find the cheapest active plan that grants the given capability."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slug, name, price_inr, features
            FROM plans
            WHERE active = TRUE
            ORDER BY price_inr ASC
            """
        )
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


def _as_uuid(user_id: str) -> UUID:
    return UUID(str(user_id).strip())


async def save_checkout_context(*, order_id: str, user_id: str, plan_id: str) -> None:
    pool = get_pool()
    uid = _as_uuid(user_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payment_checkout_context (order_id, user_id, plan_id)
            VALUES ($1, $2, $3::uuid)
            ON CONFLICT (order_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                plan_id = EXCLUDED.plan_id,
                created_at = NOW()
            """,
            order_id.strip(),
            uid,
            plan_id,
        )


async def complete_plan_purchase(*, user_id: str, order_id: str) -> Tuple[bool, Optional[str]]:
    """
    Verify JusPay payment and create a user_plan_grants row. Plan comes from payment_checkout_context.
    """
    uid = _as_uuid(user_id)
    oid = order_id.strip()
    if not oid:
        return False, "order_id is required"

    pool = get_pool()
    async with pool.acquire() as conn:
        ctx = await conn.fetchrow(
            """
            SELECT plan_id, user_id
            FROM payment_checkout_context
            WHERE order_id = $1 AND user_id = $2
            """,
            oid,
            uid,
        )

        existing = await conn.fetchrow(
            """
            SELECT user_id, plan_id, credits_remaining
            FROM user_plan_grants
            WHERE order_id = $1
            """,
            oid,
        )

        if existing:
            if existing["user_id"] != uid:
                return False, "This payment was already applied to another account."
            await conn.execute("DELETE FROM payment_checkout_context WHERE order_id = $1", oid)
            return True, None

        if not ctx:
            return False, "No pending checkout for this order. Start checkout again while signed in."

        plan_row = await conn.fetchrow(
            """
            SELECT id, slug, price_inr, credits_allocation, features
            FROM plans
            WHERE id = $1 AND active = TRUE
            """,
            ctx["plan_id"],
        )
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
            await conn.execute(
                """
                INSERT INTO user_plan_grants (user_id, plan_id, order_id, credits_remaining)
                VALUES ($1, $2::uuid, $3, $4)
                """,
                uid,
                str(plan_row["id"]),
                oid,
                credits_alloc,
            )
            await conn.execute("DELETE FROM payment_checkout_context WHERE order_id = $1", oid)
    except asyncpg.exceptions.UniqueViolationError:
        async with pool.acquire() as conn2:
            g = await conn2.fetchrow(
                "SELECT user_id FROM user_plan_grants WHERE order_id = $1",
                oid,
            )
        if g and g["user_id"] == uid:
            return True, None
        return False, "This payment was already applied."

    return True, None


def _aggregate_capability(rows: list[dict[str, Any]], cap_key: str) -> dict[str, Any]:
    matching = []
    for r in rows:
        feats = _normalize_features(r.get("features"))
        if not _feature_truthy(feats, cap_key):
            continue
        matching.append(r)

    if not matching:
        return {"allowed": False, "unlimited": False, "credits_remaining": 0}

    if any(r.get("credits_remaining") is None for r in matching):
        return {"allowed": True, "unlimited": True, "credits_remaining": None}

    total = sum(int(r["credits_remaining"] or 0) for r in matching)
    return {"allowed": total > 0, "unlimited": False, "credits_remaining": total}


async def get_user_entitlements(*, user_id: str) -> dict[str, Any]:
    pool = get_pool()
    uid = _as_uuid(user_id)

    # Check for admin-granted subscription first
    admin_grant = await admin_subscription_grant_service.get_admin_subscription_grant(user_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                g.id,
                g.user_id,
                g.order_id,
                g.credits_remaining,
                g.granted_at,
                p.slug AS plan_slug,
                p.name AS plan_name,
                p.price_inr,
                p.credits_allocation,
                p.features
            FROM user_plan_grants g
            JOIN plans p ON p.id = g.plan_id
            WHERE g.user_id = $1
            ORDER BY g.granted_at DESC
            """,
            uid,
        )

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

    # If user has admin grant, add a synthetic "unlimited" grant entry
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
        grants_out.append(
            {
                "plan_slug": g["plan_slug"],
                "plan_name": g["plan_name"],
                "order_id": g["order_id"],
                "credits_remaining": cr,
                "credits_unlimited": cr is None,
                "granted_at": g.get("granted_at"),
                "features": g.get("features") or {},
            }
        )

    # If admin grant exists, all capabilities are unlocked
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
