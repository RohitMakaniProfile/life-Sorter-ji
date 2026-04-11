from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

skill_calls_t = Table("skill_calls")

_SQL_INSERT_RETURNING_ID = """
    INSERT INTO skill_calls (
        conversation_id, message_id, skill_id, run_id,
        input, state, output, started_at, created_at, updated_at
    ) VALUES ($1,$2,$3,$4,$5::jsonb,'running',$6::jsonb,$7,NOW(),NOW())
    RETURNING id
"""

_SQL_RESET_FOR_RETRY = """
    UPDATE skill_calls
    SET state       = 'running',
        error       = NULL,
        ended_at    = NULL,
        duration_ms = NULL,
        output      = '[]'::jsonb,
        run_id      = $2,
        message_id  = $3,
        input       = $4::jsonb,
        started_at  = NOW(),
        updated_at  = NOW()
    WHERE id = $1::bigint
"""

_SQL_RELINK_MESSAGE = "UPDATE skill_calls SET message_id = $2, updated_at = NOW() WHERE id = $1::bigint"
_SQL_SELECT_OUTPUT = "SELECT output FROM skill_calls WHERE id = $1::bigint"
_SQL_SELECT_TIMING = "SELECT started_at, output FROM skill_calls WHERE id = $1::bigint"
_SQL_DURATION_FROM_STARTED = "SELECT (EXTRACT(EPOCH FROM (NOW() - $1)) * 1000)::int AS ms"

_SQL_APPEND_STREAMED_TEXT = """
    UPDATE skill_calls
    SET streamed_text = COALESCE(streamed_text, '') || $2,
        updated_at = NOW()
    WHERE id = $1::bigint
"""

_SQL_ADD_STREAMED_TEXT_COLUMN = "ALTER TABLE skill_calls ADD COLUMN IF NOT EXISTS streamed_text TEXT NOT NULL DEFAULT ''"

_SQL_UPDATE_RESULT = """
    UPDATE skill_calls
    SET state = $2,
        error = $3,
        ended_at = $4,
        duration_ms = $5,
        output = $6::jsonb,
        updated_at = NOW()
    WHERE id = $1::bigint
"""

_TIMEOUT_MINUTES = 5
_TIMEOUT_ERROR = f"Timed out: no updates received for over {_TIMEOUT_MINUTES} minutes"

_SQL_AUTO_TIMEOUT_BASE = """
    UPDATE skill_calls
    SET state       = 'error',
        error       = '{msg}',
        ended_at    = NOW(),
        duration_ms = (EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::integer,
        updated_at  = NOW()
    WHERE state = 'running'
      AND updated_at < NOW() - INTERVAL '{mins} minutes'
""".format(msg=_TIMEOUT_ERROR, mins=_TIMEOUT_MINUTES)


async def insert_returning_id(conn, conversation_id: str, message_id: str,
                               skill_id: str, run_id: str,
                               input_json: str, started_at: datetime) -> str:
    row = await conn.fetchrow(
        _SQL_INSERT_RETURNING_ID,
        conversation_id, message_id, skill_id, run_id, input_json, "[]", started_at,
    )
    return str(row["id"])


async def reset_for_retry(conn, skill_call_id: int, run_id: str,
                           new_message_id: str, input_json: str) -> None:
    await conn.execute(_SQL_RESET_FOR_RETRY, skill_call_id, run_id, new_message_id, input_json)


async def relink_message(conn, skill_call_id: int, new_message_id: str) -> None:
    await conn.execute(_SQL_RELINK_MESSAGE, skill_call_id, new_message_id)


async def get_output(conn, skill_call_id: int) -> Any:
    row = await conn.fetchrow(_SQL_SELECT_OUTPUT, skill_call_id)
    return row["output"] if row else None


async def get_timing_and_output(conn, skill_call_id: int) -> Any:
    return await conn.fetchrow(_SQL_SELECT_TIMING, skill_call_id)


async def compute_duration_ms(conn, started_at: datetime) -> int | None:
    row = await conn.fetchrow(_SQL_DURATION_FROM_STARTED, started_at)
    return int(row["ms"]) if row and row["ms"] is not None else None


async def append_streamed_text(conn, skill_call_id: int, text: str) -> None:
    try:
        await conn.execute(_SQL_APPEND_STREAMED_TEXT, skill_call_id, text)
    except Exception:
        await conn.execute(_SQL_ADD_STREAMED_TEXT_COLUMN)
        await conn.execute(_SQL_APPEND_STREAMED_TEXT, skill_call_id, text)


async def update_result(conn, skill_call_id: int, state: str, error: str | None,
                         ended_at: datetime, duration_ms: int | None, output_json: str) -> None:
    await conn.execute(_SQL_UPDATE_RESULT, skill_call_id, state, error,
                       ended_at, duration_ms, output_json)


async def update_output(conn, skill_call_id: int, output_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(skill_calls_t)
        .set(skill_calls_t.output, Parameter("%s"))
        .set(skill_calls_t.updated_at, fn.Now())
        .where(skill_calls_t.id == Parameter("%s")),
        [output_json, skill_call_id],
    )
    await conn.execute(q.sql, *q.params)


async def find_by_message_id(conn, message_id: str) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(skill_calls_t).select("*")
        .where(skill_calls_t.message_id == Parameter("%s"))
        .orderby(skill_calls_t.created_at, order=Order.asc),
        [message_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_recent_playwright_done(conn, limit: int) -> list[Any]:
    """Fetch recently completed scrape-playwright calls (for cache lookups)."""
    q = build_query(
        PostgreSQLQuery.from_(skill_calls_t)
        .select(skill_calls_t.id, skill_calls_t.input, skill_calls_t.output, skill_calls_t.updated_at)
        .where(skill_calls_t.skill_id == "scrape-playwright")
        .where(skill_calls_t.state == "done")
        .orderby(skill_calls_t.updated_at, order=Order.desc)
        .limit(int(max(1, limit))),
    )
    return list(await conn.fetch(q.sql, *q.params))


async def auto_timeout_stale(
    conn, *, message_id: str | None = None,
    user_id: str | None = None, skill_call_id: int | None = None,
) -> None:
    """Mark timed-out running calls as error. Scope by message, user, or specific call."""
    if skill_call_id is not None:
        await conn.execute(_SQL_AUTO_TIMEOUT_BASE + " AND id = $1", skill_call_id)
    elif message_id:
        await conn.execute(_SQL_AUTO_TIMEOUT_BASE + " AND message_id = $1", message_id)
    elif user_id:
        await conn.execute(
            _SQL_AUTO_TIMEOUT_BASE
            + " AND conversation_id IN (SELECT id FROM conversations WHERE user_id = $1)",
            user_id,
        )


async def find_by_user_paginated(conn, user_id: str, limit: int, offset: int) -> tuple[list[Any], int]:
    """Admin: list skill calls for a user's conversations with total count."""
    from app.repositories.conversations_repository import conversations_t
    sc = skill_calls_t.as_("sc")
    c = conversations_t.as_("c")
    rows_q = build_query(
        PostgreSQLQuery.from_(sc)
        .join(c).on(c.id == sc.conversation_id)
        .select(sc.id, sc.conversation_id, sc.message_id, sc.skill_id,
                sc.input, sc.state, sc.started_at, sc.ended_at, sc.duration_ms)
        .where(c.user_id == Parameter("%s"))
        .orderby(sc.started_at, order=Order.desc)
        .limit(Parameter("%s")).offset(Parameter("%s")),
        [user_id, limit, offset],
    )
    count_q = build_query(
        PostgreSQLQuery.from_(sc)
        .join(c).on(c.id == sc.conversation_id)
        .select(fn.Count(1))
        .where(c.user_id == Parameter("%s")),
        [user_id],
    )
    rows = list(await conn.fetch(rows_q.sql, *rows_q.params))
    total = int(await conn.fetchval(count_q.sql, *count_q.params) or 0)
    return rows, total


async def find_detail_by_id(conn, skill_call_id: int) -> Any:
    """Admin: full detail for one skill call."""
    q = build_query(
        PostgreSQLQuery.from_(skill_calls_t)
        .select(
            skill_calls_t.id, skill_calls_t.conversation_id, skill_calls_t.message_id,
            skill_calls_t.skill_id, skill_calls_t.run_id, skill_calls_t.input,
            skill_calls_t.streamed_text, skill_calls_t.state, skill_calls_t.output,
            skill_calls_t.error, skill_calls_t.started_at, skill_calls_t.ended_at,
            skill_calls_t.duration_ms, skill_calls_t.created_at,
        )
        .where(skill_calls_t.id == Parameter("%s")).limit(1),
        [skill_call_id],
    )
    return await conn.fetchrow(q.sql, *q.params)