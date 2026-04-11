from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table, functions as fn, CustomFunction
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter, LiteralValue

from app.sql_builder import build_query


def _cast_jsonb(param: Parameter) -> LiteralValue:
    """Cast a parameter to jsonb type using raw SQL."""
    return LiteralValue(f"{param}::jsonb")


messages_t = Table("messages")

# Kept as raw SQL: pg_advisory_xact_lock(hashtext(...)) is a PostgreSQL-specific
# function with no PyPika equivalent.
_SQL_ADVISORY_LOCK = "SELECT pg_advisory_xact_lock(hashtext($1))"

# Kept as raw SQL: COALESCE(streamed_text, '') || $2 uses the || string
# concatenation operator which has no PyPika equivalent.
_SQL_APPEND_STREAMED_TEXT = (
    "UPDATE messages "
    "SET streamed_text = COALESCE(streamed_text, '') || $2, "
    "    updated_at = NOW() "
    "WHERE conversation_id = $1 AND message_index = $2"
)


async def insert_atomic(
    conn, conversation_id: str, role: str, content: str,
    created_at: datetime, output_file: str | None, message_json: str,
) -> int:
    """Insert a message using advisory lock + transaction for sequential message_index."""
    async with conn.transaction():
        await conn.execute(_SQL_ADVISORY_LOCK, conversation_id)
        next_index_q = build_query(
            PostgreSQLQuery.from_(messages_t)
            .select(fn.Coalesce(fn.Max(messages_t.message_index), -1) + 1)
            .where(messages_t.conversation_id == Parameter("%s")),
            [conversation_id],
        )
        next_index = int(await conn.fetchval(next_index_q.sql, *next_index_q.params))
        insert_q = build_query(
            PostgreSQLQuery.into(messages_t)
            .columns(
                messages_t.conversation_id, messages_t.message_index, messages_t.role,
                messages_t.content, messages_t.created_at, messages_t.output_file,
                messages_t.message,
            )
            .insert(
                Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
                Parameter("%s"), Parameter("%s"), _cast_jsonb(Parameter("%s")),
            ),
            [conversation_id, next_index, role, content, created_at, output_file, message_json],
        )
        await conn.execute(insert_q.sql, *insert_q.params)
    return next_index


async def find_by_message_id(conn, conversation_id: str, message_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(messages_t)
        .select(messages_t.message_index, messages_t.message)
        .where(messages_t.conversation_id == Parameter("%s"))
        .where(messages_t.message.get_text_value("messageId") == Parameter("%s"))
        .limit(1),
        [conversation_id, message_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_form_id(conn, conversation_id: str, form_id: str) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(messages_t).select("*")
        .where(messages_t.conversation_id == Parameter("%s"))
        .where(messages_t.message.get_text_value("formId") == Parameter("%s"))
        .orderby(messages_t.message_index, order=Order.asc),
        [conversation_id, form_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_by_conversation(conn, conversation_id: str) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(messages_t).select("*")
        .where(messages_t.conversation_id == Parameter("%s"))
        .orderby(messages_t.message_index, order=Order.asc),
        [conversation_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def get_last_message(conn, conversation_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(messages_t).select(messages_t.message)
        .where(messages_t.conversation_id == Parameter("%s"))
        .orderby(messages_t.message_index, order=Order.desc).limit(1),
        [conversation_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_content(conn, conversation_id: str, message_index: int,
                          content: str, output_file: str | None, message_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(messages_t)
        .set(messages_t.content, Parameter("%s"))
        .set(messages_t.output_file, fn.Coalesce(Parameter("%s"), messages_t.output_file))
        .set(messages_t.message, _cast_jsonb(Parameter("%s")))
        .where(messages_t.conversation_id == Parameter("%s"))
        .where(messages_t.message_index == Parameter("%s")),
        [content, output_file, message_json, conversation_id, message_index],
    )
    await conn.execute(q.sql, *q.params)


async def update_meta(conn, conversation_id: str, message_index: int, message_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(messages_t)
        .set(messages_t.message, _cast_jsonb(Parameter("%s")))
        .where(messages_t.conversation_id == Parameter("%s"))
        .where(messages_t.message_index == Parameter("%s")),
        [message_json, conversation_id, message_index],
    )
    await conn.execute(q.sql, *q.params)


async def count_by_conversation(conn, conversation_id: str) -> int:
    q = build_query(
        PostgreSQLQuery.from_(messages_t).select(fn.Count("*"))
        .where(messages_t.conversation_id == Parameter("%s")),
        [conversation_id],
    )
    return int(await conn.fetchval(q.sql, *q.params))


async def find_conversation_and_user_by_message_id(conn, message_id: str) -> Any:
    """JOIN messages + conversations to resolve conversation_id and user_id from messageId."""
    from app.repositories.conversations_repository import conversations_t
    q = build_query(
        PostgreSQLQuery.from_(messages_t)
        .join(conversations_t).on(conversations_t.id == messages_t.conversation_id)
        .select(messages_t.conversation_id, conversations_t.user_id)
        .where(messages_t.message.get_text_value("messageId") == Parameter("%s"))
        .limit(1),
        [message_id],
    )
    return await conn.fetchrow(q.sql, *q.params)