from __future__ import annotations

from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

system_config_t = Table("system_config")


async def get_value(conn, key: str) -> str | None:
    q = build_query(
        PostgreSQLQuery.from_(system_config_t).select(system_config_t.value)
        .where(system_config_t.key == Parameter("%s")),
        [key],
    )
    v = await conn.fetchval(q.sql, *q.params)
    return str(v) if v is not None else None


async def get_value_and_type(conn, key: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(system_config_t)
        .select(system_config_t.value, system_config_t.type)
        .where(system_config_t.key == Parameter("%s")),
        [key],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def get_existing_type(conn, key: str) -> str | None:
    q = build_query(
        PostgreSQLQuery.from_(system_config_t).select(system_config_t.type)
        .where(system_config_t.key == Parameter("%s")),
        [key],
    )
    v = await conn.fetchval(q.sql, *q.params)
    return str(v) if v is not None else None


async def upsert_with_type(conn, key: str, value: str, config_type: str, description: str) -> None:
    q = build_query(
        PostgreSQLQuery.into(system_config_t)
        .columns(system_config_t.key, system_config_t.value,
                 system_config_t.type, system_config_t.description)
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"))
        .on_conflict(system_config_t.key)
        .do_update(system_config_t.value)
        .do_update(system_config_t.type)
        .do_update(system_config_t.description),
        [key, value, config_type, description],
    )
    await conn.execute(q.sql, *q.params)


async def upsert_without_type(conn, key: str, value: str, description: str) -> None:
    """Upsert keeping the existing type (only updates value and description)."""
    q = build_query(
        PostgreSQLQuery.into(system_config_t)
        .columns(system_config_t.key, system_config_t.value, system_config_t.description)
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"))
        .on_conflict(system_config_t.key)
        .do_update(system_config_t.value)
        .do_update(system_config_t.description),
        [key, value, description],
    )
    await conn.execute(q.sql, *q.params)


async def find_all_ordered(conn) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(system_config_t)
        .select(system_config_t.key, system_config_t.value,
                system_config_t.type, system_config_t.description, system_config_t.updated_at)
        .orderby(system_config_t.key, order=Order.asc)
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_entry_by_key(conn, key: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(system_config_t)
        .select(system_config_t.key, system_config_t.value, system_config_t.type,
                system_config_t.description, system_config_t.updated_at)
        .where(system_config_t.key == Parameter("%s")).limit(1),
        [key],
    )
    return await conn.fetchrow(q.sql, *q.params)