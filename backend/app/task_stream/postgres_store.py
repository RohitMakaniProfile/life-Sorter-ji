from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional

from asyncpg import UniqueViolationError

from app.config import REDIS_TASKSTREAM_MAX_BACKLOG, REDIS_TASKSTREAM_TTL_SECONDS
from app.db import get_pool
from app.task_stream.events import TaskStreamEvent

_PG_CURSOR_PREFIX = "pg:"


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
            await conn.execute(
                "DELETE FROM task_stream_spawn_locks WHERE expires_at < NOW()",
            )
            try:
                await conn.execute(
                    """
                    INSERT INTO task_stream_spawn_locks (lock_key, expires_at)
                    VALUES ($1, NOW() + INTERVAL '10 seconds')
                    """,
                    lock_key,
                )
                return True
            except UniqueViolationError:
                return False

    async def release_spawn_lock(self, lock_key: str) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM task_stream_spawn_locks WHERE lock_key = $1", lock_key)

    async def resolve_stream_id(
        self,
        task_type: str,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        pool = get_pool()
        async with pool.acquire() as conn:
            if session_id:
                sid = (session_id or "").strip()
                if sid:
                    row = await conn.fetchrow(
                        """
                        SELECT m.stream_id
                        FROM task_stream_maps m
                        JOIN task_stream_streams s ON s.stream_id = m.stream_id
                        WHERE m.task_type = $1
                          AND m.map_kind = 'session'
                          AND m.map_key = $2
                          AND m.expires_at > NOW()
                          AND s.expires_at > NOW()
                        LIMIT 1
                        """,
                        task_type,
                        sid,
                    )
                    if row:
                        return str(row["stream_id"])

            if user_id:
                uid = (user_id or "").strip()
                if uid:
                    row = await conn.fetchrow(
                        """
                        SELECT m.stream_id
                        FROM task_stream_maps m
                        JOIN task_stream_streams s ON s.stream_id = m.stream_id
                        WHERE m.task_type = $1
                          AND m.map_kind = 'user'
                          AND m.map_key = $2
                          AND m.expires_at > NOW()
                          AND s.expires_at > NOW()
                        LIMIT 1
                        """,
                        task_type,
                        uid,
                    )
                    if row:
                        return str(row["stream_id"])
        return None

    async def create_stream_and_meta(
        self,
        stream_id: str,
        *,
        task_type: str,
        session_id: Optional[str],
        user_id: Optional[str],
        status: str = "running",
    ) -> None:
        exp = _expires_at()
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO task_stream_streams (
                    stream_id, task_type, session_id, user_id, status,
                    last_seq, last_event_id, created_at, expires_at
                )
                VALUES ($1, $2, $3, $4, $5, 0, NULL, NOW(), $6)
                """,
                stream_id,
                task_type,
                (session_id or "").strip(),
                (user_id or "").strip(),
                status,
                exp,
            )

    async def set_status(self, stream_id: str, status: str) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE task_stream_streams
                SET status = $2, expires_at = $3
                WHERE stream_id = $1
                """,
                stream_id,
                status,
                _expires_at(),
            )

    async def get_status(self, stream_id: str) -> str:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT status FROM task_stream_streams
                WHERE stream_id = $1 AND expires_at > NOW()
                """,
                stream_id,
            )
            return str(row["status"]) if row else ""

    async def get_meta(self, stream_id: str) -> dict[str, Any]:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT stream_id, task_type, session_id, user_id, status, last_seq, created_at, expires_at
                FROM task_stream_streams
                WHERE stream_id = $1 AND expires_at > NOW()
                """,
                stream_id,
            )
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
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        exp = _expires_at()
        pool = get_pool()
        async with pool.acquire() as conn:
            if session_id:
                sid = (session_id or "").strip()
                if sid:
                    await conn.execute(
                        """
                        INSERT INTO task_stream_maps (task_type, map_kind, map_key, stream_id, expires_at)
                        VALUES ($1, 'session', $2, $3, $4)
                        ON CONFLICT (task_type, map_kind, map_key) DO UPDATE
                        SET stream_id = EXCLUDED.stream_id,
                            expires_at = EXCLUDED.expires_at
                        """,
                        task_type,
                        sid,
                        stream_id,
                        exp,
                    )
            if user_id:
                uid = (user_id or "").strip()
                if uid:
                    await conn.execute(
                        """
                        INSERT INTO task_stream_maps (task_type, map_kind, map_key, stream_id, expires_at)
                        VALUES ($1, 'user', $2, $3, $4)
                        ON CONFLICT (task_type, map_kind, map_key) DO UPDATE
                        SET stream_id = EXCLUDED.stream_id,
                            expires_at = EXCLUDED.expires_at
                        """,
                        task_type,
                        uid,
                        stream_id,
                        exp,
                    )

    async def xadd_event(self, stream_id: str, event_type: str, data: dict[str, Any]) -> TaskStreamEvent:
        event_obj = {"type": event_type, **data}
        event_json = json.dumps(event_obj, separators=(",", ":"), ensure_ascii=False)
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                seq = await conn.fetchval(
                    """
                    UPDATE task_stream_streams
                    SET last_seq = last_seq + 1,
                        expires_at = $2
                    WHERE stream_id = $1 AND expires_at > NOW()
                    RETURNING last_seq
                    """,
                    stream_id,
                    _expires_at(),
                )
                if seq is None:
                    raise RuntimeError(f"task stream not found or expired: {stream_id}")
                row = await conn.fetchrow(
                    """
                    INSERT INTO task_stream_events (stream_id, seq, event)
                    VALUES ($1, $2, $3::jsonb)
                    RETURNING id
                    """,
                    stream_id,
                    int(seq),
                    event_json,
                )
                eid = int(row["id"])
                await conn.execute(
                    """
                    UPDATE task_stream_streams SET last_event_id = $2, expires_at = $3 WHERE stream_id = $1
                    """,
                    stream_id,
                    eid,
                    _expires_at(),
                )
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
            rows = await conn.fetch(
                """
                SELECT id, seq, event
                FROM task_stream_events
                WHERE stream_id = $1
                ORDER BY id DESC
                LIMIT $2
                """,
                stream_id,
                max(1, int(max_backlog)),
            )
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
                rows = await conn.fetch(
                    """
                    SELECT id, seq, event
                    FROM task_stream_events
                    WHERE stream_id = $1 AND id > $2
                    ORDER BY id ASC
                    LIMIT $3
                    """,
                    stream_id,
                    last_id,
                    max(1, int(count)),
                )
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
            result = await conn.execute(
                """
                UPDATE task_stream_streams
                SET status = 'error',
                    expires_at = NOW() + INTERVAL '1 hour'
                WHERE status = 'running'
                  AND created_at < NOW() - INTERVAL '%s minutes'
                """ % int(max_age_minutes)
            )
            # Result format: "UPDATE N"
            count = int(result.split()[-1]) if result else 0
            return count

