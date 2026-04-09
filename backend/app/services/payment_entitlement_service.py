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
from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.sql_builder import build_query
from app.services import juspay_service
from app.services import admin_subscription_grant_service

logger = structlog.get_logger()

CAPABILITY_KEYS = ("deep_analysis_report", "execute_report_actions")
plans_t = Table("plans")
user_plan_grants_t = Table("user_plan_grants")
payment_checkout_context_t = Table("payment_checkout_context")

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
        grants_q = build_query(
            PostgreSQLQuery.from_(user_plan_grants_t)
            .join(plans_t)
            .on((plans_t.id == user_plan_grants_t.plan_id) & (plans_t.active == True))
            .select(
                user_plan_grants_t.id,
                plans_t.slug.as_("plan_slug"),
                plans_t.name.as_("plan_name"),
                user_plan_grants_t.credits_remaining,
                plans_t.features,
            )
            .where(user_plan_grants_t.user_id == Parameter("%s"))
            .orderby(user_plan_grants_t.granted_at, order=Order.desc),
            [uid],
        )
        rows = await conn.fetch(grants_q.sql, *grants_q.params)

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
        plans_for_cap_q = build_query(
            PostgreSQLQuery.from_(plans_t)
            .select(plans_t.slug, plans_t.name, plans_t.price_inr, plans_t.features)
            .where(plans_t.active == True)
            .orderby(plans_t.price_inr, order=Order.asc)
        )
        rows = await conn.fetch(plans_for_cap_q.sql, *plans_for_cap_q.params)
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
        save_checkout_q = build_query(
            PostgreSQLQuery.into(payment_checkout_context_t)
            .columns(
                payment_checkout_context_t.order_id,
                payment_checkout_context_t.user_id,
                payment_checkout_context_t.plan_id,
                payment_checkout_context_t.created_at,
            )
            .insert(Parameter("%s"), Parameter("%s"), Parameter("%s").cast("uuid"), fn.Now())
            .on_conflict(payment_checkout_context_t.order_id)
            .do_update(payment_checkout_context_t.user_id)
            .do_update(payment_checkout_context_t.plan_id)
            .do_update(payment_checkout_context_t.created_at),
            [order_id.strip(), uid, plan_id],
        )
        await conn.execute(save_checkout_q.sql, *save_checkout_q.params)


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
        checkout_ctx_q = build_query(
            PostgreSQLQuery.from_(payment_checkout_context_t)
            .select(payment_checkout_context_t.plan_id, payment_checkout_context_t.user_id)
            .where(payment_checkout_context_t.order_id == Parameter("%s"))
            .where(payment_checkout_context_t.user_id == Parameter("%s")),
            [oid, uid],
        )
        ctx = await conn.fetchrow(checkout_ctx_q.sql, *checkout_ctx_q.params)

        existing_grant_q = build_query(
            PostgreSQLQuery.from_(user_plan_grants_t)
            .select(
                user_plan_grants_t.user_id,
                user_plan_grants_t.plan_id,
                user_plan_grants_t.credits_remaining,
            )
            .where(user_plan_grants_t.order_id == Parameter("%s")),
            [oid],
        )
        existing = await conn.fetchrow(existing_grant_q.sql, *existing_grant_q.params)

        if existing:
            if existing["user_id"] != uid:
                return False, "This payment was already applied to another account."
            delete_checkout_ctx_q = build_query(
                PostgreSQLQuery.from_(payment_checkout_context_t)
                .delete()
                .where(payment_checkout_context_t.order_id == Parameter("%s")),
                [oid],
            )
            await conn.execute(delete_checkout_ctx_q.sql, *delete_checkout_ctx_q.params)
            return True, None

        if not ctx:
            return False, "No pending checkout for this order. Start checkout again while signed in."

        active_plan_q = build_query(
            PostgreSQLQuery.from_(plans_t)
            .select(
                plans_t.id,
                plans_t.slug,
                plans_t.price_inr,
                plans_t.credits_allocation,
                plans_t.features,
            )
            .where(plans_t.id == Parameter("%s"))
            .where(plans_t.active == True),
            [ctx["plan_id"]],
        )
        plan_row = await conn.fetchrow(active_plan_q.sql, *active_plan_q.params)
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
            insert_grant_q = build_query(
                PostgreSQLQuery.into(user_plan_grants_t)
                .columns(
                    user_plan_grants_t.user_id,
                    user_plan_grants_t.plan_id,
                    user_plan_grants_t.order_id,
                    user_plan_grants_t.credits_remaining,
                )
                .insert(
                    Parameter("%s"),
                    Parameter("%s").cast("uuid"),
                    Parameter("%s"),
                    Parameter("%s"),
                ),
                [uid, str(plan_row["id"]), oid, credits_alloc],
            )
            await conn.execute(insert_grant_q.sql, *insert_grant_q.params)
            delete_checkout_ctx_q = build_query(
                PostgreSQLQuery.from_(payment_checkout_context_t)
                .delete()
                .where(payment_checkout_context_t.order_id == Parameter("%s")),
                [oid],
            )
            await conn.execute(delete_checkout_ctx_q.sql, *delete_checkout_ctx_q.params)
    except asyncpg.exceptions.UniqueViolationError:
        async with pool.acquire() as conn2:
            existing_owner_q = build_query(
                PostgreSQLQuery.from_(user_plan_grants_t)
                .select(user_plan_grants_t.user_id)
                .where(user_plan_grants_t.order_id == Parameter("%s")),
                [oid],
            )
            g = await conn2.fetchrow(existing_owner_q.sql, *existing_owner_q.params)
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
        entitlements_q = build_query(
            PostgreSQLQuery.from_(user_plan_grants_t)
            .join(plans_t)
            .on(plans_t.id == user_plan_grants_t.plan_id)
            .select(
                user_plan_grants_t.id,
                user_plan_grants_t.user_id,
                user_plan_grants_t.order_id,
                user_plan_grants_t.credits_remaining,
                user_plan_grants_t.granted_at,
                plans_t.slug.as_("plan_slug"),
                plans_t.name.as_("plan_name"),
                plans_t.price_inr,
                plans_t.credits_allocation,
                plans_t.features,
            )
            .where(user_plan_grants_t.user_id == Parameter("%s"))
            .orderby(user_plan_grants_t.granted_at, order=Order.desc),
            [uid],
        )
        rows = await conn.fetch(entitlements_q.sql, *entitlements_q.params)

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
