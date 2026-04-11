from __future__ import annotations

from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

plans_t = Table("plans")


async def find_all_active(conn) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(plans_t)
        .select(plans_t.slug, plans_t.name, plans_t.price_inr, plans_t.features)
        .where(plans_t.active == True)  # noqa: E712
        .orderby(plans_t.price_inr, order=Order.asc)
    )
    return list(await conn.fetch(q.sql, *q.params))


_FULL_COLS = (
    plans_t.id,
    plans_t.slug,
    plans_t.name,
    plans_t.description,
    plans_t.price_inr,
    plans_t.credits_allocation,
    plans_t.features,
    plans_t.display_order,
    plans_t.active,
)


async def list_active_full(conn) -> list[Any]:
    """List all active plans with full column set (for plan_catalog_service)."""
    q = build_query(
        PostgreSQLQuery.from_(plans_t)
        .select(*_FULL_COLS)
        .where(plans_t.active.isin([True]))
        .orderby(plans_t.display_order)
        .orderby(plans_t.name)
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_by_slug_active(conn, slug: str) -> Any:
    """Find active plan by slug with full column set."""
    q = build_query(
        PostgreSQLQuery.from_(plans_t)
        .select(*_FULL_COLS)
        .where(plans_t.slug == Parameter("%s"))
        .where(plans_t.active.isin([True])),
        [slug.strip()],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_id_full(conn, plan_id: Any) -> Any:
    """Find plan by id with full column set."""
    q = build_query(
        PostgreSQLQuery.from_(plans_t)
        .select(*_FULL_COLS)
        .where(plans_t.id == Parameter("%s")),
        [plan_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_active_by_id(conn, plan_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(plans_t)
        .select(plans_t.id, plans_t.slug, plans_t.price_inr,
                plans_t.credits_allocation, plans_t.features)
        .where(plans_t.id == Parameter("%s"))
        .where(plans_t.active == True),  # noqa: E712
        [plan_id],
    )
    return await conn.fetchrow(q.sql, *q.params)