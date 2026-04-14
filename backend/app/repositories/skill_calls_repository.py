from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter, LiteralValue

from app.sql_builder import build_query

skill_calls_t = Table("skill_calls")


def _cast_jsonb(param: Parameter) -> LiteralValue:
    """Cast a parameter to jsonb type."""
    return LiteralValue(f"{param}::jsonb")


def _cast_bigint(param: Parameter) -> LiteralValue:
    """Cast a parameter to bigint type."""
    return LiteralValue(f"{param}::bigint")


_TIMEOUT_MINUTES = 5
_TIMEOUT_ERROR = f"Timed out: no updates received for over {_TIMEOUT_MINUTES} minutes"

# Complex timeout condition - kept as LiteralValue for interval arithmetic
_TIMEOUT_CONDITION = LiteralValue(f"state = 'running' AND updated_at < NOW() - INTERVAL '{_TIMEOUT_MINUTES} minutes'")


async def insert_returning_id(conn, conversation_id: str, message_id: str,
                               skill_id: str, run_id: str,
                               input_json: str, started_at: datetime) -> str:
    q = build_query(
        PostgreSQLQuery.into(skill_calls_t)
        .columns(
            skill_calls_t.conversation_id, skill_calls_t.message_id,
            skill_calls_t.skill_id, skill_calls_t.run_id, skill_calls_t.input,
            skill_calls_t.state, skill_calls_t.output, skill_calls_t.started_at,
            skill_calls_t.created_at, skill_calls_t.updated_at,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            _cast_jsonb(Parameter("%s")), "running", _cast_jsonb(Parameter("%s")),
            Parameter("%s"), fn.Now(), fn.Now(),
        )
        .returning(skill_calls_t.id),
        [conversation_id, message_id, skill_id, run_id, input_json, "[]", started_at],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return str(row["id"])


async def reset_for_retry(conn, skill_call_id: int, run_id: str,
                           new_message_id: str, input_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(skill_calls_t)
        .set(skill_calls_t.state, "running")
        .set(skill_calls_t.error, None)
        .set(skill_calls_t.ended_at, None)
        .set(skill_calls_t.duration_ms, None)
        .set(skill_calls_t.output, LiteralValue("'[]'::jsonb"))
        .set(skill_calls_t.run_id, Parameter("%s"))
        .set(skill_calls_t.message_id, Parameter("%s"))
        .set(skill_calls_t.input, _cast_jsonb(Parameter("%s")))
        .set(skill_calls_t.started_at, fn.Now())
        .set(skill_calls_t.updated_at, fn.Now())
        .where(skill_calls_t.id == _cast_bigint(Parameter("%s"))),
        [run_id, new_message_id, input_json, skill_call_id],
    )
    await conn.execute(q.sql, *q.params)


async def relink_message(conn, skill_call_id: int, new_message_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(skill_calls_t)
        .set(skill_calls_t.message_id, Parameter("%s"))
        .set(skill_calls_t.updated_at, fn.Now())
        .where(skill_calls_t.id == _cast_bigint(Parameter("%s"))),
        [new_message_id, skill_call_id],
    )
    await conn.execute(q.sql, *q.params)


async def get_output(conn, skill_call_id: int) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(skill_calls_t)
        .select(skill_calls_t.output)
        .where(skill_calls_t.id == _cast_bigint(Parameter("%s"))),
        [skill_call_id],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return row["output"] if row else None


async def get_timing_and_output(conn, skill_call_id: int) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(skill_calls_t)
        .select(
            skill_calls_t.started_at,
            skill_calls_t.output,
            skill_calls_t.conversation_id,
            skill_calls_t.message_id,
        )
        .where(skill_calls_t.id == _cast_bigint(Parameter("%s"))),
        [skill_call_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def compute_duration_ms(conn, started_at: datetime) -> int | None:
    # Duration calculation uses PostgreSQL-specific EXTRACT - kept as raw
    row = await conn.fetchrow(
        "SELECT (EXTRACT(EPOCH FROM (NOW() - $1)) * 1000)::int AS ms",
        started_at,
    )
    return int(row["ms"]) if row and row["ms"] is not None else None


async def append_streamed_text(conn, skill_call_id: int, text: str) -> None:
    # String concatenation with || kept as raw SQL
    try:
        await conn.execute(
            "UPDATE skill_calls SET streamed_text = COALESCE(streamed_text, '') || $2, "
            "updated_at = NOW() WHERE id = $1::bigint",
            skill_call_id, text,
        )
    except Exception:
        await conn.execute(
            "ALTER TABLE skill_calls ADD COLUMN IF NOT EXISTS streamed_text TEXT NOT NULL DEFAULT ''",
        )
        await conn.execute(
            "UPDATE skill_calls SET streamed_text = COALESCE(streamed_text, '') || $2, "
            "updated_at = NOW() WHERE id = $1::bigint",
            skill_call_id, text,
        )


async def update_result(conn, skill_call_id: int, state: str, error: str | None,
                         ended_at: datetime, duration_ms: int | None, output_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(skill_calls_t)
        .set(skill_calls_t.state, Parameter("%s"))
        .set(skill_calls_t.error, Parameter("%s"))
        .set(skill_calls_t.ended_at, Parameter("%s"))
        .set(skill_calls_t.duration_ms, Parameter("%s"))
        .set(skill_calls_t.output, _cast_jsonb(Parameter("%s")))
        .set(skill_calls_t.updated_at, fn.Now())
        .where(skill_calls_t.id == _cast_bigint(Parameter("%s"))),
        [state, error, ended_at, duration_ms, output_json, skill_call_id],
    )
    await conn.execute(q.sql, *q.params)


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
    # Complex interval arithmetic kept as raw SQL
    base_sql = f"""
        UPDATE skill_calls
        SET state       = 'error',
            error       = '{_TIMEOUT_ERROR}',
            ended_at    = NOW(),
            duration_ms = (EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::integer,
            updated_at  = NOW()
        WHERE state = 'running'
          AND updated_at < NOW() - INTERVAL '{_TIMEOUT_MINUTES} minutes'
    """
    if skill_call_id is not None:
        await conn.execute(base_sql + " AND id = $1", skill_call_id)
    elif message_id:
        await conn.execute(base_sql + " AND message_id = $1", message_id)
    elif user_id:
        await conn.execute(
            base_sql + " AND conversation_id IN (SELECT id FROM conversations WHERE user_id = $1)",
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


async def insert_onboarding_skill_call(
    conn, onboarding_session_id: str, skill_id: str, run_id: str, input_json: str,
) -> int:
    """INSERT a running skill_call scoped to an onboarding session. Returns row id."""
    q = build_query(
        PostgreSQLQuery.into(skill_calls_t)
        .columns(
            skill_calls_t.onboarding_session_id, skill_calls_t.skill_id,
            skill_calls_t.run_id, skill_calls_t.input, skill_calls_t.state,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"),
            _cast_jsonb(Parameter("%s")), "running",
        )
        .returning(skill_calls_t.id),
        [onboarding_session_id, skill_id, run_id, input_json],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return int(row["id"])


async def finish_onboarding_skill_call(
    conn, skill_call_id: int, state: str, output_json: str,
    error: str | None, duration_ms: int,
) -> None:
    """Mark an onboarding skill_call as done/error and store output."""
    q = build_query(
        PostgreSQLQuery.update(skill_calls_t)
        .set(skill_calls_t.state, Parameter("%s"))
        .set(skill_calls_t.output, _cast_jsonb(Parameter("%s")))
        .set(skill_calls_t.error, Parameter("%s"))
        .set(skill_calls_t.ended_at, fn.Now())
        .set(skill_calls_t.duration_ms, Parameter("%s"))
        .set(skill_calls_t.updated_at, fn.Now())
        .where(skill_calls_t.id == _cast_bigint(Parameter("%s"))),
        [state, output_json, error, duration_ms, skill_call_id],
    )
    await conn.execute(q.sql, *q.params)


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