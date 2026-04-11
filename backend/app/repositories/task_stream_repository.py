from __future__ import annotations

from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

task_stream_streams_t = Table("task_stream_streams")


def cleanup_stale_running_sql() -> str:
    """Return SQL string for cleaning up stale running streams (used by task_stream module).

    Note: Kept as raw SQL because it uses interval arithmetic with a parameter ($1::int * INTERVAL).
    """
    return (
        "UPDATE task_stream_streams "
        "SET status = 'error', "
        "    expires_at = NOW() + INTERVAL '1 hour' "
        "WHERE status = 'running' "
        "  AND created_at < NOW() - ($1::int * INTERVAL '1 minute')"
    )


async def find_latest_by_session_and_type(conn, session_id: str, task_type: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_streams_t)
        .select(task_stream_streams_t.stream_id, task_stream_streams_t.status)
        .where(task_stream_streams_t.session_id == Parameter("%s"))
        .where(task_stream_streams_t.task_type == task_type)
        .orderby(task_stream_streams_t.created_at, order=Order.desc).limit(1),
        [session_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def count_running(conn) -> int:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_streams_t)
        .select(fn.Count(1))
        .where(task_stream_streams_t.status == "running")
    )
    return int(await conn.fetchval(q.sql, *q.params) or 0)


async def delete_by_user(conn, user_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_streams_t).delete()
        .where(task_stream_streams_t.user_id == Parameter("%s")),
        [user_id],
    )
    await conn.execute(q.sql, *q.params)