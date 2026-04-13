from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

products_t = Table("products")

_INSERT_COLS = (
    products_t.id,
    products_t.name,
    products_t.emoji,
    products_t.description,
    products_t.color,
    products_t.outcome,
    products_t.domain,
    products_t.task,
    products_t.is_active,
    products_t.sort_order,
    products_t.created_at,
    products_t.updated_at,
)


async def find_all(conn, active_only: bool = False) -> list[Any]:
    qb = (
        PostgreSQLQuery.from_(products_t)
        .select("*")
        .orderby(products_t.sort_order, order=Order.asc)
        .orderby(products_t.updated_at, order=Order.desc)
    )
    if active_only:
        qb = qb.where(products_t.is_active == Parameter("%s"))
        q = build_query(qb, [True])
    else:
        q = build_query(qb)
    return list(await conn.fetch(q.sql, *q.params))


async def find_by_id(conn, product_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(products_t).select("*")
        .where(products_t.id == Parameter("%s")),
        [product_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def insert_returning(
    conn,
    product_id: str,
    name: str,
    emoji: str,
    description: str,
    color: str,
    outcome: str,
    domain: str,
    task: str,
    is_active: bool,
    sort_order: int,
    now: datetime,
) -> Any:
    q = build_query(
        PostgreSQLQuery.into(products_t)
        .columns(*_INSERT_COLS)
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
        )
        .returning("*"),
        [
            product_id,
            name,
            emoji,
            description,
            color,
            outcome,
            domain,
            task,
            is_active,
            sort_order,
            now,
            now,
        ],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_fields(conn, product_id: str, fields: dict[str, Any], now: datetime) -> Any:
    col_map = {
        "name": products_t.name,
        "emoji": products_t.emoji,
        "description": products_t.description,
        "color": products_t.color,
        "outcome": products_t.outcome,
        "domain": products_t.domain,
        "task": products_t.task,
        "isActive": products_t.is_active,
        "sortOrder": products_t.sort_order,
    }
    qb = PostgreSQLQuery.update(products_t)
    vals: list[Any] = []
    for key, col in col_map.items():
        if key in fields:
            qb = qb.set(col, Parameter("%s"))
            vals.append(fields[key])
    if not vals:
        return None
    qb = qb.set(products_t.updated_at, Parameter("%s"))
    vals.append(now)
    vals.append(product_id)
    q = build_query(qb.where(products_t.id == Parameter("%s")).returning("*"), vals)
    return await conn.fetchrow(q.sql, *q.params)


async def delete_by_id(conn, product_id: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(products_t).delete()
        .where(products_t.id == Parameter("%s")),
        [product_id],
    )
    result = await conn.execute(q.sql, *q.params)
    return result.endswith("1")

