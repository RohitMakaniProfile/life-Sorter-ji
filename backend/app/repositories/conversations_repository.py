from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter, LiteralValue

from app.sql_builder import build_query

conversations_t = Table("conversations")


def _cast_jsonb(param: Parameter) -> LiteralValue:
    """Cast a parameter to jsonb type using raw SQL."""
    return LiteralValue(f"{param}::jsonb")


async def find_by_id(conn, conversation_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select("*")
        .where(conversations_t.id == Parameter("%s")),
        [conversation_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_latest_by_user(conn, user_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select(conversations_t.id)
        .where(conversations_t.user_id == Parameter("%s"))
        .orderby(conversations_t.updated_at, order=Order.desc).limit(1),
        [user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_latest_by_onboarding(conn, onboarding_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select(conversations_t.id)
        .where(conversations_t.onboarding_id == Parameter("%s"))
        .where(conversations_t.user_id.isnull())
        .orderby(conversations_t.updated_at, order=Order.desc).limit(1),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def list_by_user(conn, user_id: str) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select("*")
        .where(conversations_t.user_id == Parameter("%s"))
        .orderby(conversations_t.updated_at, order=Order.desc),
        [user_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def list_by_session(conn, session_id: str) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select("*")
        .where(
            (conversations_t.onboarding_id == Parameter("%s"))
            | ((conversations_t.onboarding_id == Parameter("%s")) & conversations_t.user_id.isnull())
        )
        .orderby(conversations_t.updated_at, order=Order.desc),
        [session_id, session_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def insert(conn, conv_id: str, agent_id: str, onboarding_id: str | None,
                 user_id: str | None, now: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.into(conversations_t)
        .columns(
            conversations_t.id, conversations_t.agent_id, conversations_t.onboarding_id,
            conversations_t.user_id, conversations_t.created_at, conversations_t.updated_at,
        )
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
                Parameter("%s"), Parameter("%s")),
        [conv_id, agent_id, onboarding_id, user_id, now, now],
    )
    await conn.execute(q.sql, *q.params)


async def touch(conn, conversation_id: str, now: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.updated_at, Parameter("%s"))
        .where(conversations_t.id == Parameter("%s")),
        [now, conversation_id],
    )
    await conn.execute(q.sql, *q.params)


async def get_title(conn, conversation_id: str) -> str | None:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select(conversations_t.title)
        .where(conversations_t.id == Parameter("%s")),
        [conversation_id],
    )
    return await conn.fetchval(q.sql, *q.params)


async def set_title(conn, conversation_id: str, title: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.title, Parameter("%s"))
        .where(conversations_t.id == Parameter("%s")),
        [title, conversation_id],
    )
    await conn.execute(q.sql, *q.params)


async def get_stage_outputs(conn, conversation_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select(conversations_t.last_stage_outputs)
        .where(conversations_t.id == Parameter("%s")),
        [conversation_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_stage_outputs(conn, conversation_id: str, outputs_json: str,
                                output_file: str | None, now: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.last_stage_outputs, _cast_jsonb(Parameter("%s")))
        .set(conversations_t.last_output_file, Parameter("%s"))
        .set(conversations_t.updated_at, Parameter("%s"))
        .where(conversations_t.id == Parameter("%s")),
        [outputs_json, output_file, now, conversation_id],
    )
    await conn.execute(q.sql, *q.params)


async def delete_by_id(conn, conversation_id: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).delete()
        .where(conversations_t.id == Parameter("%s")),
        [conversation_id],
    )
    result = await conn.execute(q.sql, *q.params)
    return result.endswith("1")


async def delete_by_user_id(conn, user_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).delete()
        .where(conversations_t.user_id == Parameter("%s")),
        [user_id],
    )
    await conn.execute(q.sql, *q.params)


async def promote_session_to_user(conn, session_id: str, user_id: str) -> str:
    """Update session-scoped conversations to belong to the authenticated user."""
    # Complex condition: user_id IS NULL OR NULLIF(BTRIM(user_id::text), '') IS NULL
    null_check = LiteralValue("(user_id IS NULL OR NULLIF(BTRIM(user_id::text), '') IS NULL)")
    q = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.user_id, Parameter("%s"))
        .set(conversations_t.updated_at, fn.Now())
        .where(conversations_t.session_id == Parameter("%s"))
        .where(null_check),
        [user_id, session_id],
    )
    return await conn.execute(q.sql, *q.params)


async def exists_by_user(conn, user_id: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(conversations_t).select(1)
        .where(conversations_t.user_id == Parameter("%s")).limit(1),
        [user_id],
    )
    return bool(await conn.fetchval(q.sql, *q.params))