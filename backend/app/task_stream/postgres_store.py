from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional

from asyncpg import UniqueViolationError
from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.config import REDIS_TASKSTREAM_MAX_BACKLOG, REDIS_TASKSTREAM_TTL_SECONDS
from app.db import get_pool
from app.repositories.task_stream_table import cleanup_stale_running_streams_sql
from app.sql_builder import build_query
from app.task_stream.events import TaskStreamEvent

_PG_CURSOR_PREFIX = "pg:"
task_stream_spawn_locks_t = Table("task_stream_spawn_locks")
task_stream_maps_t = Table("task_stream_maps")
task_stream_streams_t = Table("task_stream_streams")
task_stream_events_t = Table("task_stream_events")


def _expires_at() -> datetime:
    return datetime.utcnow() + timedelta(seconds=max(60, int(REDIS_TASKSTREAM_TTL_SECONDS)))


def _cursor_from_row_id(row_id: int) -> str:
    return f"{_PG_CURSOR_PREFIX}{row_id}"


def _row_id_from_cursor(cursor: str) -> int:
    if not cursor:
        return 0
    s = str(cursor).strip()
    if s.startswith(_PG_CURSOR_PREFIX):
        try:
            return int(s[len(_PG_CURSOR_PREFIX) :], 10)
        except ValueError:
            return 0
    return 0


class PostgresTaskStreamStore:
    """
    Postgres-backed task stream store (SSE backlog + resume).
    Same behavioural contract as RedisTaskStreamStore for TaskStreamService / router.
    """

    async def try_acquire_spawn_lock(self, lock_key: str) -> bool:
        pool = get_pool()
        async with pool.acquire() as conn:
            delete_expired_q = build_query(
                PostgreSQLQuery.from_(task_stream_spawn_locks_t)
                .delete()
                .where(task_stream_spawn_locks_t.expires_at < fn.Now())
            )
            await conn.execute(delete_expired_q.sql, *delete_expired_q.params)
            try:
                insert_lock_q = build_query(
                    PostgreSQLQuery.into(task_stream_spawn_locks_t)
                    .columns(task_stream_spawn_locks_t.lock_key, task_stream_spawn_locks_t.expires_at)
                    .insert(Parameter("%s"), Parameter("%s")),
                    [lock_key, datetime.utcnow() + timedelta(seconds=10)],
                )
                await conn.execute(insert_lock_q.sql, *insert_lock_q.params)
                return True
            except UniqueViolationError:
                return False

    async def release_spawn_lock(self, lock_key: str) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            delete_lock_q = build_query(
                PostgreSQLQuery.from_(task_stream_spawn_locks_t)
                .delete()
                .where(task_stream_spawn_locks_t.lock_key == Parameter("%s")),
                [lock_key],
            )
            await conn.execute(delete_lock_q.sql, *delete_lock_q.params)

    async def resolve_stream_id(
        self,
        task_type: str,
        *,
        onboarding_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        pool = get_pool()
        async with pool.acquire() as conn:
            if onboarding_id:
                oid = (onboarding_id or "").strip()
                if oid:
                    stream_q = build_query(
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
                        [task_type, oid],
                    )
                    row = await conn.fetchrow(stream_q.sql, *stream_q.params)
                    if row:
                        return str(row["stream_id"])

            if user_id:
                uid = (user_id or "").strip()
                if uid:
                    stream_q = build_query(
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
                        [task_type, uid],
                    )
                    row = await conn.fetchrow(stream_q.sql, *stream_q.params)
                    if row:
                        return str(row["stream_id"])
        return None

    async def create_stream_and_meta(
        self,
        stream_id: str,
        *,
        task_type: str,
        onboarding_id: Optional[str],
        user_id: Optional[str],
        status: str = "running",
    ) -> None:
        exp = _expires_at()
        pool = get_pool()
        async with pool.acquire() as conn:
            create_q = build_query(
                PostgreSQLQuery.into(task_stream_streams_t)
                .columns(
                    "stream_id",
                    "task_type",
                    "session_id",
                    "user_id",
                    "status",
                    "last_seq",
                    "last_event_id",
                    "created_at",
                    "expires_at",
                )
                .insert(
                    Parameter("%s"),
                    Parameter("%s"),
                    Parameter("%s"),
                    Parameter("%s"),
                    Parameter("%s"),
                    0,
                    None,
                    fn.Now(),
                    Parameter("%s"),
                ),
                [stream_id, task_type, (onboarding_id or "").strip(), (user_id or "").strip(), status, exp],
            )
            await conn.execute(create_q.sql, *create_q.params)

    async def set_status(self, stream_id: str, status: str) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            set_status_q = build_query(
                PostgreSQLQuery.update(task_stream_streams_t)
                .set(task_stream_streams_t.status, Parameter("%s"))
                .set(task_stream_streams_t.expires_at, Parameter("%s"))
                .where(task_stream_streams_t.stream_id == Parameter("%s")),
                [status, _expires_at(), stream_id],
            )
            await conn.execute(set_status_q.sql, *set_status_q.params)

    async def get_status(self, stream_id: str) -> str:
        pool = get_pool()
        async with pool.acquire() as conn:
            get_status_q = build_query(
                PostgreSQLQuery.from_(task_stream_streams_t)
                .select(task_stream_streams_t.status)
                .where(task_stream_streams_t.stream_id == Parameter("%s"))
                .where(task_stream_streams_t.expires_at > fn.Now()),
                [stream_id],
            )
            row = await conn.fetchrow(get_status_q.sql, *get_status_q.params)
            return str(row["status"]) if row else ""

    async def get_meta(self, stream_id: str) -> dict[str, Any]:
        pool = get_pool()
        async with pool.acquire() as conn:
            get_meta_q = build_query(
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
            row = await conn.fetchrow(get_meta_q.sql, *get_meta_q.params)
        if not row:
            return {"stream_id": stream_id}
        d = dict(row)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        d["stream_id"] = stream_id
        d["last_cursor"] = ""
        if d.get("last_seq") is not None:
            d["last_seq"] = str(d["last_seq"])
        return d

    async def set_actor_mapping(
        self,
        task_type: str,
        *,
        stream_id: str,
        onboarding_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        exp = _expires_at()
        pool = get_pool()
        async with pool.acquire() as conn:
            if onboarding_id:
                oid = (onboarding_id or "").strip()
                if oid:
                    upsert_session_q = build_query(
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
                        [task_type, oid, stream_id, exp],
                    )
                    await conn.execute(upsert_session_q.sql, *upsert_session_q.params)
            if user_id:
                uid = (user_id or "").strip()
                if uid:
                    upsert_user_q = build_query(
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
                        [task_type, uid, stream_id, exp],
                    )
                    await conn.execute(upsert_user_q.sql, *upsert_user_q.params)

    async def clear_actor_mapping(
        self,
        task_type: str,
        *,
        onboarding_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        """Remove actor mapping so next start creates a fresh stream."""
        pool = get_pool()
        async with pool.acquire() as conn:
            if onboarding_id:
                oid = (onboarding_id or "").strip()
                if oid:
                    clear_session_q = build_query(
                        PostgreSQLQuery.from_(task_stream_maps_t)
                        .delete()
                        .where(task_stream_maps_t.task_type == Parameter("%s"))
                        .where(task_stream_maps_t.map_kind == "session")
                        .where(task_stream_maps_t.map_key == Parameter("%s")),
                        [task_type, oid],
                    )
                    await conn.execute(clear_session_q.sql, *clear_session_q.params)
            if user_id:
                uid = (user_id or "").strip()
                if uid:
                    clear_user_q = build_query(
                        PostgreSQLQuery.from_(task_stream_maps_t)
                        .delete()
                        .where(task_stream_maps_t.task_type == Parameter("%s"))
                        .where(task_stream_maps_t.map_kind == "user")
                        .where(task_stream_maps_t.map_key == Parameter("%s")),
                        [task_type, uid],
                    )
                    await conn.execute(clear_user_q.sql, *clear_user_q.params)

    async def xadd_event(self, stream_id: str, event_type: str, data: dict[str, Any]) -> TaskStreamEvent:
        event_obj = {"type": event_type, **data}
        event_json = json.dumps(event_obj, separators=(",", ":"), ensure_ascii=False)
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                bump_seq_q = build_query(
                    PostgreSQLQuery.update(task_stream_streams_t)
                    .set(task_stream_streams_t.last_seq, task_stream_streams_t.last_seq + 1)
                    .set(task_stream_streams_t.expires_at, Parameter("%s"))
                    .where(task_stream_streams_t.stream_id == Parameter("%s"))
                    .where(task_stream_streams_t.expires_at > fn.Now())
                    .returning(task_stream_streams_t.last_seq),
                    [_expires_at(), stream_id],
                )
                seq = await conn.fetchval(bump_seq_q.sql, *bump_seq_q.params)
                if seq is None:
                    raise RuntimeError(f"task stream not found or expired: {stream_id}")
                insert_event_q = build_query(
                    PostgreSQLQuery.into(task_stream_events_t)
                    .columns("stream_id", "seq", "event")
                    .insert(Parameter("%s"), Parameter("%s"), Parameter("%s").cast("jsonb"))
                    .returning(task_stream_events_t.id),
                    [stream_id, int(seq), event_json],
                )
                row = await conn.fetchrow(insert_event_q.sql, *insert_event_q.params)
                eid = int(row["id"])
                set_last_event_q = build_query(
                    PostgreSQLQuery.update(task_stream_streams_t)
                    .set(task_stream_streams_t.last_event_id, Parameter("%s"))
                    .set(task_stream_streams_t.expires_at, Parameter("%s"))
                    .where(task_stream_streams_t.stream_id == Parameter("%s")),
                    [eid, _expires_at(), stream_id],
                )
                await conn.execute(set_last_event_q.sql, *set_last_event_q.params)
        cursor = _cursor_from_row_id(eid)
        return TaskStreamEvent(cursor=cursor, seq=int(seq), type=event_type, data=data)

    async def xget_backlog(
        self,
        stream_id: str,
        *,
        max_backlog: int = REDIS_TASKSTREAM_MAX_BACKLOG,
    ) -> list[TaskStreamEvent]:
        pool = get_pool()
        async with pool.acquire() as conn:
            backlog_q = build_query(
                PostgreSQLQuery.from_(task_stream_events_t)
                .select(task_stream_events_t.id, task_stream_events_t.seq, task_stream_events_t.event)
                .where(task_stream_events_t.stream_id == Parameter("%s"))
                .orderby(task_stream_events_t.id, order=Order.desc)
                .limit(Parameter("%s")),
                [stream_id, max(1, int(max_backlog))],
            )
            rows = await conn.fetch(backlog_q.sql, *backlog_q.params)
        rows = list(reversed(rows))
        out: list[TaskStreamEvent] = []
        for r in rows:
            ev = r["event"]
            if isinstance(ev, str):
                ev = json.loads(ev)
            elif ev is None:
                ev = {}
            else:
                ev = dict(ev)
            out.append(
                TaskStreamEvent(
                    cursor=_cursor_from_row_id(int(r["id"])),
                    seq=int(r["seq"] or 0),
                    type=str(ev.get("type") or ""),
                    data={k: v for k, v in ev.items() if k != "type"},
                )
            )
        return out

    async def xread_new(
        self,
        stream_id: str,
        *,
        cursor: str,
        block_ms: int,
        count: int = 50,
    ) -> list[TaskStreamEvent]:
        last_id = _row_id_from_cursor(cursor)
        deadline = time.monotonic() + max(0, int(block_ms)) / 1000.0
        pool = get_pool()
        while True:
            async with pool.acquire() as conn:
                new_events_q = build_query(
                    PostgreSQLQuery.from_(task_stream_events_t)
                    .select(task_stream_events_t.id, task_stream_events_t.seq, task_stream_events_t.event)
                    .where(task_stream_events_t.stream_id == Parameter("%s"))
                    .where(task_stream_events_t.id > Parameter("%s"))
                    .orderby(task_stream_events_t.id, order=Order.asc)
                    .limit(Parameter("%s")),
                    [stream_id, last_id, max(1, int(count))],
                )
                rows = await conn.fetch(new_events_q.sql, *new_events_q.params)
            if rows:
                events: list[TaskStreamEvent] = []
                for r in rows:
                    ev = r["event"]
                    if isinstance(ev, str):
                        ev = json.loads(ev)
                    elif ev is None:
                        ev = {}
                    else:
                        ev = dict(ev)
                    events.append(
                        TaskStreamEvent(
                            cursor=_cursor_from_row_id(int(r["id"])),
                            seq=int(r["seq"] or 0),
                            type=str(ev.get("type") or ""),
                            data={k: v for k, v in ev.items() if k != "type"},
                        )
                    )
                return events
            if time.monotonic() >= deadline:
                return []
            await asyncio.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    async def iter_events(
        self,
        stream_id: str,
        *,
        cursor: Optional[str] = None,
        block_ms: int = 5000,
        count: int = 50,
    ) -> AsyncIterator[TaskStreamEvent]:
        status = await self.get_status(stream_id)
        if status in ("done", "error", "cancelled"):
            last = await self.xget_backlog(stream_id, max_backlog=1)
            for e in last:
                yield e
            return

        if not cursor:
            backlog = await self.xget_backlog(stream_id)
            for e in backlog:
                yield e
                if e.type in ("done", "error"):
                    return
            if backlog:
                cursor = backlog[-1].cursor
            else:
                cursor = f"{_PG_CURSOR_PREFIX}0"

        while True:
            effective_cursor = cursor or f"{_PG_CURSOR_PREFIX}0"
            new_events = await self.xread_new(
                stream_id,
                cursor=effective_cursor,
                block_ms=block_ms,
                count=count,
            )
            if not new_events:
                yield TaskStreamEvent(cursor="", seq=0, type="ping", data={})
                continue
            for e in new_events:
                yield e
                cursor = e.cursor
                if e.type in ("done", "error"):
                    return

    async def cleanup_stale_running_streams(self, max_age_minutes: int = 30) -> int:
        """
        Mark 'running' streams older than max_age_minutes as 'error'.

        This handles the case where backend was restarted while streams were active.
        Returns the count of streams cleaned up.
        """
        pool = get_pool()
        async with pool.acquire() as conn:
            # Keep raw SQL: dynamic INTERVAL parameterization is awkward in PyPika for this predicate.
            result = await conn.execute(cleanup_stale_running_streams_sql(), int(max_age_minutes))
            # Result format: "UPDATE N"
            count = int(result.split()[-1]) if result else 0
            return count

