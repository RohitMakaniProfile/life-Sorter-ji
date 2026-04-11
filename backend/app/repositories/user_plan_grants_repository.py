from __future__ import annotations

from typing import Any
from uuid import UUID

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query
from app.repositories.plans_repository import plans_t

user_plan_grants_t = Table("user_plan_grants")


async def find_by_user_with_plan(conn, user_id: UUID) -> list[Any]:
    """Return grants joined with plan details, ordered newest-first."""
    q = build_query(
        PostgreSQLQuery.from_(user_plan_grants_t)
        .join(plans_t).on((plans_t.id == user_plan_grants_t.plan_id) & (plans_t.active == True))  # noqa: E712
        .select(
            user_plan_grants_t.id,
            plans_t.slug.as_("plan_slug"),
            plans_t.name.as_("plan_name"),
            user_plan_grants_t.credits_remaining,
            plans_t.features,
        )
        .where(user_plan_grants_t.user_id == Parameter("%s"))
        .orderby(user_plan_grants_t.granted_at, order=Order.desc),
        [user_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_entitlements_by_user(conn, user_id: UUID) -> list[Any]:
    """Full entitlement join for get_user_entitlements."""
    q = build_query(
        PostgreSQLQuery.from_(user_plan_grants_t)
        .join(plans_t).on(plans_t.id == user_plan_grants_t.plan_id)
        .select(
            user_plan_grants_t.id, user_plan_grants_t.user_id,
            user_plan_grants_t.order_id, user_plan_grants_t.credits_remaining,
            user_plan_grants_t.granted_at,
            plans_t.slug.as_("plan_slug"), plans_t.name.as_("plan_name"),
            plans_t.price_inr, plans_t.credits_allocation, plans_t.features,
        )
        .where(user_plan_grants_t.user_id == Parameter("%s"))
        .orderby(user_plan_grants_t.granted_at, order=Order.desc),
        [user_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_by_order_id(conn, order_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(user_plan_grants_t)
        .select(user_plan_grants_t.user_id, user_plan_grants_t.plan_id,
                user_plan_grants_t.credits_remaining)
        .where(user_plan_grants_t.order_id == Parameter("%s")),
        [order_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_owner_by_order_id(conn, order_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(user_plan_grants_t)
        .select(user_plan_grants_t.user_id)
        .where(user_plan_grants_t.order_id == Parameter("%s")),
        [order_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def insert(conn, user_id: UUID, plan_id: str, order_id: str,
                 credits_remaining: Any) -> None:
    q = build_query(
        PostgreSQLQuery.into(user_plan_grants_t)
        .columns(user_plan_grants_t.user_id, user_plan_grants_t.plan_id,
                 user_plan_grants_t.order_id, user_plan_grants_t.credits_remaining)
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s")),
        [user_id, plan_id, order_id, credits_remaining],
    )
    await conn.execute(q.sql, *q.params)