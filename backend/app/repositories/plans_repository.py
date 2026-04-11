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