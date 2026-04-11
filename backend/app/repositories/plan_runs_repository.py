from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter, LiteralValue

from app.sql_builder import build_query

plan_runs_t = Table("plan_runs")


def _cast_jsonb(param: Parameter) -> LiteralValue:
    """Cast a parameter to jsonb type."""
    return LiteralValue(f"{param}::jsonb")


async def insert_returning(
    conn, plan_id: str, conversation_id: str, user_message_id: str,
    plan_message_id: str, plan_markdown: str, plan_json_str: str, now: datetime,
) -> Any:
    q = build_query(
        PostgreSQLQuery.into(plan_runs_t)
        .columns(
            plan_runs_t.id, plan_runs_t.conversation_id, plan_runs_t.user_message_id,
            plan_runs_t.plan_message_id, plan_runs_t.status, plan_runs_t.plan_markdown,
            plan_runs_t.plan_json, plan_runs_t.created_at, plan_runs_t.updated_at,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            "draft", Parameter("%s"), _cast_jsonb(Parameter("%s")),
            Parameter("%s"), Parameter("%s"),
        )
        .returning("*"),
        [plan_id, conversation_id, user_message_id, plan_message_id,
         plan_markdown, plan_json_str, now, now],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_id(conn, plan_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(plan_runs_t).select("*")
        .where(plan_runs_t.id == Parameter("%s")),
        [plan_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def claim_for_execution(conn, plan_id: str, now: datetime) -> Any:
    """Atomically transition draft/approved → executing. Returns row if succeeded."""
    q = build_query(
        PostgreSQLQuery.update(plan_runs_t)
        .set(plan_runs_t.status, "executing")
        .set(plan_runs_t.updated_at, Parameter("%s"))
        .where(plan_runs_t.id == Parameter("%s"))
        .where(plan_runs_t.status.isin(["draft", "approved"]))
        .returning(plan_runs_t.id),
        [now, plan_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_fields(conn, plan_id: str, fields: dict[str, Any]) -> None:
    """Dynamic UPDATE for plan_run. Fields: status, planMarkdown, executionMessageId, planJson, errorMessage."""
    col_map = {
        "status": (plan_runs_t.status, False),
        "planMarkdown": (plan_runs_t.plan_markdown, False),
        "executionMessageId": (plan_runs_t.execution_message_id, False),
        "planJson": (plan_runs_t.plan_json, True),  # True = needs ::jsonb cast
        "errorMessage": (plan_runs_t.error_message, False),
    }

    # Ensure optional columns exist
    if "executionMessageId" in fields:
        try:
            await conn.execute("ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS execution_message_id TEXT")
        except Exception:
            pass
    if "errorMessage" in fields:
        try:
            await conn.execute("ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS error_message TEXT")
        except Exception:
            pass

    qb = PostgreSQLQuery.update(plan_runs_t)
    vals: list[Any] = []
    for key, (col, is_jsonb) in col_map.items():
        if key in fields:
            if is_jsonb:
                qb = qb.set(col, _cast_jsonb(Parameter("%s")))
            else:
                qb = qb.set(col, Parameter("%s"))
            vals.append(fields[key])

    qb = qb.set(plan_runs_t.updated_at, Parameter("%s"))
    vals.append(datetime.now())
    vals.append(plan_id)
    q = build_query(
        qb.where(plan_runs_t.id == Parameter("%s")),
        vals,
    )
    await conn.execute(q.sql, *q.params)


async def mark_error(conn, plan_id: str, error_message: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(plan_runs_t)
        .set(plan_runs_t.status, "error")
        .set(plan_runs_t.error_message, Parameter("%s"))
        .set(plan_runs_t.updated_at, fn.Now())
        .where(plan_runs_t.id == Parameter("%s")),
        [error_message, plan_id],
    )
    await conn.execute(q.sql, *q.params)


async def mark_as_interrupted(conn, plan_id: str, error_message: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(plan_runs_t)
        .set(plan_runs_t.status, "interrupted")
        .set(plan_runs_t.error_message, Parameter("%s"))
        .set(plan_runs_t.updated_at, fn.Now())
        .where(plan_runs_t.id == Parameter("%s"))
        .where(plan_runs_t.status == "executing"),
        [error_message, plan_id],
    )
    await conn.execute(q.sql, *q.params)


async def cleanup_stale_executing(conn) -> str:
    q = build_query(
        PostgreSQLQuery.update(plan_runs_t)
        .set(plan_runs_t.status, "interrupted")
        .set(plan_runs_t.error_message, "Process interrupted (backend restart). You can retry this plan.")
        .set(plan_runs_t.updated_at, fn.Now())
        .where(plan_runs_t.status == "executing")
    )
    return await conn.execute(q.sql, *q.params)


async def ensure_columns(conn) -> None:
    """Add optional columns if they don't exist (called on startup)."""
    try:
        await conn.execute("ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS error_message TEXT")
    except Exception:
        pass


async def find_recent_errors(conn, limit: int = 20) -> list[Any]:
    """Admin observability: recent failed plan runs."""
    from pypika import Order
    q = build_query(
        PostgreSQLQuery.from_(plan_runs_t)
        .select(plan_runs_t.id, plan_runs_t.status, plan_runs_t.updated_at)
        .where(plan_runs_t.status == "error")
        .orderby(plan_runs_t.updated_at, order=Order.desc)
        .limit(limit)
    )
    return list(await conn.fetch(q.sql, *q.params))