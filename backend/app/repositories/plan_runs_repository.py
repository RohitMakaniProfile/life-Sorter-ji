from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

plan_runs_t = Table("plan_runs")

_SQL_INSERT_RETURNING = """
    INSERT INTO plan_runs (
        id, conversation_id, user_message_id, plan_message_id,
        status, plan_markdown, plan_json, created_at, updated_at
    ) VALUES ($1,$2,$3,$4,'draft',$5,$6::jsonb,$7,$8)
    RETURNING *
"""

_SQL_CLAIM_FOR_EXECUTION = """
    UPDATE plan_runs
    SET status = 'executing', updated_at = $2
    WHERE id = $1
      AND status IN ('draft', 'approved')
    RETURNING id
"""

_SQL_CLEANUP_STALE_EXECUTING = """
    UPDATE plan_runs
    SET status = 'interrupted',
        error_message = 'Process interrupted (backend restart). You can retry this plan.',
        updated_at = NOW()
    WHERE status = 'executing'
"""

_SQL_ADD_EXECUTION_MSG_COL = "ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS execution_message_id TEXT"
_SQL_ADD_ERROR_MSG_COL = "ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS error_message TEXT"


async def insert_returning(
    conn, plan_id: str, conversation_id: str, user_message_id: str,
    plan_message_id: str, plan_markdown: str, plan_json_str: str, now: datetime,
) -> Any:
    return await conn.fetchrow(
        _SQL_INSERT_RETURNING,
        plan_id, conversation_id, user_message_id, plan_message_id,
        plan_markdown, plan_json_str, now, now,
    )


async def find_by_id(conn, plan_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(plan_runs_t).select("*")
        .where(plan_runs_t.id == Parameter("%s")),
        [plan_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def claim_for_execution(conn, plan_id: str, now: datetime) -> Any:
    """Atomically transition draft/approved → executing. Returns row if succeeded."""
    return await conn.fetchrow(_SQL_CLAIM_FOR_EXECUTION, plan_id, now)


async def update_fields(conn, plan_id: str, fields: dict[str, Any]) -> None:
    """Dynamic UPDATE for plan_run. Fields: status, planMarkdown, executionMessageId, planJson, errorMessage."""
    col_map = {
        "status": ("status", False),
        "planMarkdown": ("plan_markdown", False),
        "executionMessageId": ("execution_message_id", False),
        "planJson": ("plan_json", True),  # True = needs ::jsonb cast
        "errorMessage": ("error_message", False),
    }
    set_parts: list[str] = []
    values: list[Any] = []
    for key, (col, is_jsonb) in col_map.items():
        if key in fields:
            cast = "::jsonb" if is_jsonb else ""
            set_parts.append(f"{col} = ${len(values) + 1}{cast}")
            values.append(fields[key])

    if "executionMessageId" in fields:
        try:
            await conn.execute(_SQL_ADD_EXECUTION_MSG_COL)
        except Exception:
            pass
    if "errorMessage" in fields:
        try:
            await conn.execute(_SQL_ADD_ERROR_MSG_COL)
        except Exception:
            pass

    set_parts.append(f"updated_at = ${len(values) + 1}")
    values.append(datetime.now())
    values.append(plan_id)
    sql = f"UPDATE plan_runs SET {', '.join(set_parts)} WHERE id = ${len(values)}"
    await conn.execute(sql, *values)


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
    return await conn.execute(_SQL_CLEANUP_STALE_EXECUTING)


async def ensure_columns(conn) -> None:
    """Add optional columns if they don't exist (called on startup)."""
    try:
        await conn.execute(_SQL_ADD_ERROR_MSG_COL)
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