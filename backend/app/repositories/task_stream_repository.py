from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

task_stream_streams_t = Table("task_stream_streams")
task_stream_maps_t = Table("task_stream_maps")
task_stream_spawn_locks_t = Table("task_stream_spawn_locks")


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


_task_stream_events_t = Table("task_stream_events")


def _cast_jsonb(param: Parameter) -> Any:
    from pypika.terms import LiteralValue
    return LiteralValue(f"{param}::jsonb")


async def insert_event(conn, stream_id: str, seq: int, event_json: str) -> int:
    """INSERT a task stream event with JSONB cast. Returns the new row id."""
    q = build_query(
        PostgreSQLQuery.into(_task_stream_events_t)
        .columns(
            _task_stream_events_t.stream_id,
            _task_stream_events_t.seq,
            _task_stream_events_t.event,
        )
        .insert(Parameter("%s"), Parameter("%s"), _cast_jsonb(Parameter("%s")))
        .returning(_task_stream_events_t.id),
        [stream_id, seq, event_json],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return int(row["id"])


# ── Spawn locks ───────────────────────────────────────────────────────────────

async def delete_expired_spawn_locks(conn) -> None:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_spawn_locks_t)
        .delete()
        .where(task_stream_spawn_locks_t.expires_at < fn.Now())
    )
    await conn.execute(q.sql, *q.params)


async def insert_spawn_lock(conn, lock_key: str, expires_at: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.into(task_stream_spawn_locks_t)
        .columns(task_stream_spawn_locks_t.lock_key, task_stream_spawn_locks_t.expires_at)
        .insert(Parameter("%s"), Parameter("%s")),
        [lock_key, expires_at],
    )
    await conn.execute(q.sql, *q.params)


async def delete_spawn_lock(conn, lock_key: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_spawn_locks_t)
        .delete()
        .where(task_stream_spawn_locks_t.lock_key == Parameter("%s")),
        [lock_key],
    )
    await conn.execute(q.sql, *q.params)


# ── Stream maps (actor → stream_id) ─────────────────────────────────────────

async def find_stream_id_by_session(conn, task_type: str, session_key: str) -> Optional[str]:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_maps_t)
        .join(task_stream_streams_t)
        .on(task_stream_streams_t.stream_id == task_stream_maps_t.stream_id)
        .select(task_stream_maps_t.stream_id)
        .where(task_stream_maps_t.task_type == Parameter("%s"))
        .where(task_stream_maps_t.map_kind == "session")
        .where(task_stream_maps_t.map_key == Parameter("%s"))
        .where(task_stream_maps_t.expires_at > fn.Now())
        .where(task_stream_streams_t.expires_at > fn.Now())
        .limit(1),
        [task_type, session_key],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return str(row["stream_id"]) if row else None


async def find_stream_id_by_user(conn, task_type: str, user_key: str) -> Optional[str]:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_maps_t)
        .join(task_stream_streams_t)
        .on(task_stream_streams_t.stream_id == task_stream_maps_t.stream_id)
        .select(task_stream_maps_t.stream_id)
        .where(task_stream_maps_t.task_type == Parameter("%s"))
        .where(task_stream_maps_t.map_kind == "user")
        .where(task_stream_maps_t.map_key == Parameter("%s"))
        .where(task_stream_maps_t.expires_at > fn.Now())
        .where(task_stream_streams_t.expires_at > fn.Now())
        .limit(1),
        [task_type, user_key],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return str(row["stream_id"]) if row else None


async def upsert_session_map(conn, task_type: str, session_key: str, stream_id: str, expires_at: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.into(task_stream_maps_t)
        .columns(
            task_stream_maps_t.task_type,
            task_stream_maps_t.map_kind,
            task_stream_maps_t.map_key,
            task_stream_maps_t.stream_id,
            task_stream_maps_t.expires_at,
        )
        .insert(Parameter("%s"), "session", Parameter("%s"), Parameter("%s"), Parameter("%s"))
        .on_conflict(
            task_stream_maps_t.task_type,
            task_stream_maps_t.map_kind,
            task_stream_maps_t.map_key,
        )
        .do_update(task_stream_maps_t.stream_id)
        .do_update(task_stream_maps_t.expires_at),
        [task_type, session_key, stream_id, expires_at],
    )
    await conn.execute(q.sql, *q.params)


async def upsert_user_map(conn, task_type: str, user_key: str, stream_id: str, expires_at: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.into(task_stream_maps_t)
        .columns(
            task_stream_maps_t.task_type,
            task_stream_maps_t.map_kind,
            task_stream_maps_t.map_key,
            task_stream_maps_t.stream_id,
            task_stream_maps_t.expires_at,
        )
        .insert(Parameter("%s"), "user", Parameter("%s"), Parameter("%s"), Parameter("%s"))
        .on_conflict(
            task_stream_maps_t.task_type,
            task_stream_maps_t.map_kind,
            task_stream_maps_t.map_key,
        )
        .do_update(task_stream_maps_t.stream_id)
        .do_update(task_stream_maps_t.expires_at),
        [task_type, user_key, stream_id, expires_at],
    )
    await conn.execute(q.sql, *q.params)


async def delete_session_map(conn, task_type: str, session_key: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_maps_t)
        .delete()
        .where(task_stream_maps_t.task_type == Parameter("%s"))
        .where(task_stream_maps_t.map_kind == "session")
        .where(task_stream_maps_t.map_key == Parameter("%s")),
        [task_type, session_key],
    )
    await conn.execute(q.sql, *q.params)


async def delete_user_map(conn, task_type: str, user_key: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_maps_t)
        .delete()
        .where(task_stream_maps_t.task_type == Parameter("%s"))
        .where(task_stream_maps_t.map_kind == "user")
        .where(task_stream_maps_t.map_key == Parameter("%s")),
        [task_type, user_key],
    )
    await conn.execute(q.sql, *q.params)


# ── Streams ───────────────────────────────────────────────────────────────────

async def create_stream(
    conn,
    stream_id: str,
    task_type: str,
    session_id: str,
    user_id: str,
    status: str,
    expires_at: datetime,
) -> None:
    q = build_query(
        PostgreSQLQuery.into(task_stream_streams_t)
        .columns(
            "stream_id", "task_type", "session_id", "user_id",
            "status", "last_seq", "last_event_id", "created_at", "expires_at",
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), 0, None, fn.Now(), Parameter("%s"),
        ),
        [stream_id, task_type, session_id, user_id, status, expires_at],
    )
    await conn.execute(q.sql, *q.params)


async def set_stream_status(conn, stream_id: str, status: str, expires_at: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.update(task_stream_streams_t)
        .set(task_stream_streams_t.status, Parameter("%s"))
        .set(task_stream_streams_t.expires_at, Parameter("%s"))
        .where(task_stream_streams_t.stream_id == Parameter("%s")),
        [status, expires_at, stream_id],
    )
    await conn.execute(q.sql, *q.params)


async def get_stream_status(conn, stream_id: str) -> Optional[str]:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_streams_t)
        .select(task_stream_streams_t.status)
        .where(task_stream_streams_t.stream_id == Parameter("%s"))
        .where(task_stream_streams_t.expires_at > fn.Now()),
        [stream_id],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return str(row["status"]) if row else None


async def get_stream_meta(conn, stream_id: str) -> Optional[Any]:
    q = build_query(
        PostgreSQLQuery.from_(task_stream_streams_t)
        .select(
            task_stream_streams_t.stream_id,
            task_stream_streams_t.task_type,
            task_stream_streams_t.session_id,
            task_stream_streams_t.user_id,
            task_stream_streams_t.status,
            task_stream_streams_t.last_seq,
            task_stream_streams_t.created_at,
            task_stream_streams_t.expires_at,
        )
        .where(task_stream_streams_t.stream_id == Parameter("%s"))
        .where(task_stream_streams_t.expires_at > fn.Now()),
        [stream_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def bump_seq(conn, stream_id: str, expires_at: datetime) -> Optional[int]:
    """Increment last_seq and return new value. Returns None if stream not found/expired."""
    q = build_query(
        PostgreSQLQuery.update(task_stream_streams_t)
        .set(task_stream_streams_t.last_seq, task_stream_streams_t.last_seq + 1)
        .set(task_stream_streams_t.expires_at, Parameter("%s"))
        .where(task_stream_streams_t.stream_id == Parameter("%s"))
        .where(task_stream_streams_t.expires_at > fn.Now())
        .returning(task_stream_streams_t.last_seq),
        [expires_at, stream_id],
    )
    return await conn.fetchval(q.sql, *q.params)


async def set_last_event(conn, stream_id: str, event_id: int, expires_at: datetime) -> None:
    q = build_query(
        PostgreSQLQuery.update(task_stream_streams_t)
        .set(task_stream_streams_t.last_event_id, Parameter("%s"))
        .set(task_stream_streams_t.expires_at, Parameter("%s"))
        .where(task_stream_streams_t.stream_id == Parameter("%s")),
        [event_id, expires_at, stream_id],
    )
    await conn.execute(q.sql, *q.params)


# ── Events read ───────────────────────────────────────────────────────────────

async def fetch_backlog(conn, stream_id: str, max_backlog: int) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(_task_stream_events_t)
        .select(_task_stream_events_t.id, _task_stream_events_t.seq, _task_stream_events_t.event)
        .where(_task_stream_events_t.stream_id == Parameter("%s"))
        .orderby(_task_stream_events_t.id, order=Order.desc)
        .limit(Parameter("%s")),
        [stream_id, max(1, int(max_backlog))],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def fetch_new_events(conn, stream_id: str, after_id: int, count: int) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(_task_stream_events_t)
        .select(_task_stream_events_t.id, _task_stream_events_t.seq, _task_stream_events_t.event)
        .where(_task_stream_events_t.stream_id == Parameter("%s"))
        .where(_task_stream_events_t.id > Parameter("%s"))
        .orderby(_task_stream_events_t.id, order=Order.asc)
        .limit(Parameter("%s")),
        [stream_id, after_id, max(1, int(count))],
    )
    return list(await conn.fetch(q.sql, *q.params))