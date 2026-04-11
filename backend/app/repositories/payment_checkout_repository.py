from __future__ import annotations

from typing import Any
from uuid import UUID

from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

payment_checkout_context_t = Table("payment_checkout_context")


async def upsert(conn, order_id: str, user_id: UUID, plan_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.into(payment_checkout_context_t)
        .columns(
            payment_checkout_context_t.order_id,
            payment_checkout_context_t.user_id,
            payment_checkout_context_t.plan_id,
            payment_checkout_context_t.created_at,
        )
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), fn.Now())
        .on_conflict(payment_checkout_context_t.order_id)
        .do_update(payment_checkout_context_t.user_id)
        .do_update(payment_checkout_context_t.plan_id)
        .do_update(payment_checkout_context_t.created_at),
        [order_id, user_id, plan_id],
    )
    await conn.execute(q.sql, *q.params)


async def find_by_order_and_user(conn, order_id: str, user_id: UUID) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(payment_checkout_context_t)
        .select(payment_checkout_context_t.plan_id, payment_checkout_context_t.user_id)
        .where(payment_checkout_context_t.order_id == Parameter("%s"))
        .where(payment_checkout_context_t.user_id == Parameter("%s")),
        [order_id, user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def delete_by_order_id(conn, order_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(payment_checkout_context_t).delete()
        .where(payment_checkout_context_t.order_id == Parameter("%s")),
        [order_id],
    )
    await conn.execute(q.sql, *q.params)