from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from app.config import (
    REDIS_TASKSTREAM_MAX_BACKLOG,
    REDIS_TASKSTREAM_MAX_STREAM_LEN,
    REDIS_TASKSTREAM_PREFIX,
    REDIS_TASKSTREAM_TTL_SECONDS,
)
from app.task_stream.redis_client import get_redis


@dataclass(frozen=True)
class TaskStreamEvent:
    cursor: str
    seq: int
    type: str
    data: dict[str, Any]


class RedisTaskStreamStore:
    """
    Low-level Redis operations for:
    - durable event persistence (Redis Streams),
    - realtime fanout (optional channel),
    - actor -> stream_id mapping for re-attachment after refresh.
    """

    def _stream_key(self, stream_id: str) -> str:
        return f"{REDIS_TASKSTREAM_PREFIX}:stream:{stream_id}"

    def _meta_key(self, stream_id: str) -> str:
        return f"{REDIS_TASKSTREAM_PREFIX}:meta:{stream_id}"

    def _seq_key(self, stream_id: str) -> str:
        return f"{REDIS_TASKSTREAM_PREFIX}:seq:{stream_id}"

    def _map_session_key(self, task_type: str, session_id: str) -> str:
        return f"{REDIS_TASKSTREAM_PREFIX}:map:{task_type}:session:{session_id}"

    def _map_user_key(self, task_type: str, user_id: str) -> str:
        return f"{REDIS_TASKSTREAM_PREFIX}:map:{task_type}:user:{user_id}"

    async def resolve_stream_id(
        self,
        task_type: str,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        if session_id:
            redis = await get_redis()
            sid = (session_id or "").strip()
            if sid:
                v = await redis.get(self._map_session_key(task_type, sid))
                if v:
                    return str(v)

        if user_id:
            redis = await get_redis()
            uid = (user_id or "").strip()
            if uid:
                v = await redis.get(self._map_user_key(task_type, uid))
                if v:
                    return str(v)

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
        redis = await get_redis()
        meta = {
            "task_type": task_type,
            "status": status,
            "session_id": session_id or "",
            "user_id": user_id or "",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        await redis.hset(self._meta_key(stream_id), mapping=meta)
        await redis.expire(self._meta_key(stream_id), REDIS_TASKSTREAM_TTL_SECONDS)

    async def set_status(self, stream_id: str, status: str) -> None:
        redis = await get_redis()
        await redis.hset(self._meta_key(stream_id), mapping={"status": status})
        await redis.expire(self._meta_key(stream_id), REDIS_TASKSTREAM_TTL_SECONDS)

    async def get_status(self, stream_id: str) -> str:
        redis = await get_redis()
        v = await redis.hget(self._meta_key(stream_id), "status")
        return str(v or "")

    async def get_meta(self, stream_id: str) -> dict[str, Any]:
        redis = await get_redis()
        meta = await redis.hgetall(self._meta_key(stream_id))
        # `decode_responses=True` => values are str
        out: dict[str, Any] = dict(meta or {})
        out["stream_id"] = stream_id
        return out

    async def set_actor_mapping(
        self,
        task_type: str,
        *,
        stream_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        redis = await get_redis()
        ttl = REDIS_TASKSTREAM_TTL_SECONDS
        if session_id:
            sid = (session_id or "").strip()
            if sid:
                await redis.set(self._map_session_key(task_type, sid), stream_id, ex=ttl)
        if user_id:
            uid = (user_id or "").strip()
            if uid:
                await redis.set(self._map_user_key(task_type, uid), stream_id, ex=ttl)

    async def xadd_event(self, stream_id: str, event_type: str, data: dict[str, Any]) -> TaskStreamEvent:
        redis = await get_redis()

        seq = await redis.incr(self._seq_key(stream_id))
        event = {"type": event_type, **data}
        event_json = json.dumps(event, separators=(",", ":"), ensure_ascii=False)

        entry_id = await redis.xadd(
            self._stream_key(stream_id),
            fields={"seq": str(seq), "event": event_json},
            maxlen=REDIS_TASKSTREAM_MAX_STREAM_LEN,
            approximate=True,
        )

        # Keep meta cursor in sync for debugging/resume UX.
        await redis.hset(self._meta_key(stream_id), mapping={"last_cursor": str(entry_id), "last_seq": str(seq)})
        await redis.expire(self._meta_key(stream_id), REDIS_TASKSTREAM_TTL_SECONDS)
        await redis.expire(self._stream_key(stream_id), REDIS_TASKSTREAM_TTL_SECONDS)
        await redis.expire(self._seq_key(stream_id), REDIS_TASKSTREAM_TTL_SECONDS)

        # Parse event back into the typed structure.
        return TaskStreamEvent(cursor=str(entry_id), seq=int(seq), type=event_type, data=data)

    async def xget_backlog(
        self,
        stream_id: str,
        *,
        max_backlog: int = REDIS_TASKSTREAM_MAX_BACKLOG,
    ) -> list[TaskStreamEvent]:
        """
        Fetch the most recent N events (chronological order).

        Used when the client doesn't provide a cursor (first connect / after refresh).
        """
        redis = await get_redis()
        entries = await redis.xrevrange(self._stream_key(stream_id), max="+", min="-", count=max_backlog)
        # Redis returns newest-first; convert to oldest-first for the UI.
        entries = list(reversed(entries))

        out: list[TaskStreamEvent] = []
        for entry_id, fields in entries:
            # `decode_responses=True` => fields values are str
            seq = int(fields.get("seq") or 0)
            event_json = fields.get("event") or "{}"
            event = json.loads(event_json)
            out.append(
                TaskStreamEvent(
                    cursor=str(entry_id),
                    seq=seq,
                    type=str(event.get("type") or ""),
                    data={k: v for k, v in event.items() if k != "type"},
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
        """
        Read events strictly after `cursor` (Redis Streams semantics).
        """
        redis = await get_redis()
        stream_key = self._stream_key(stream_id)

        # redis-py xread expects {stream_key: last_id}. It returns messages after that id.
        messages = await redis.xread({stream_key: cursor}, count=count, block=block_ms)
        if not messages:
            return []

        events: list[TaskStreamEvent] = []
        # messages: list[(stream_name, list[(entry_id, fields), ...])]
        for _stream_name, stream_messages in messages:
            for entry_id, fields in stream_messages:
                seq = int(fields.get("seq") or 0)
                event_json = fields.get("event") or "{}"
                event = json.loads(event_json)
                events.append(
                    TaskStreamEvent(
                        cursor=str(entry_id),
                        seq=seq,
                        type=str(event.get("type") or ""),
                        data={k: v for k, v in event.items() if k != "type"},
                    )
                )
        return events

    async def iter_events(
        self,
        stream_id: str,
        *,
        cursor: Optional[str] = None,
        block_ms: int = 5000,
        count: int = 50,
    ) -> AsyncIterator[TaskStreamEvent]:
        """
        Async iterator that yields:
        - backlog (if cursor missing),
        - then new events until done/error type is encountered.
        """
        # If the stream is already finished and the client re-attaches with a cursor
        # at/after the final event, we must not block forever waiting for new events.
        status = await self.get_status(stream_id)
        if status in ("done", "error", "cancelled"):
            last = await self.xget_backlog(stream_id, max_backlog=1)
            for e in last:
                yield e
            return

        # First connect: send backlog so UI catches up.
        if not cursor:
            backlog = await self.xget_backlog(stream_id)
            for e in backlog:
                yield e
                if e.type in ("done", "error"):
                    return
            # After backlog, continue from the last seen cursor.
            if backlog:
                cursor = backlog[-1].cursor
            else:
                cursor = "0-0"

        # Resume: stream forward from cursor (exclusive).
        while True:
            # If cursor is invalid/empty, fall back to 0-0.
            effective_cursor = cursor or "0-0"
            new_events = await self.xread_new(
                stream_id,
                cursor=effective_cursor,
                block_ms=block_ms,
                count=count,
            )
            if not new_events:
                # Heartbeat so the SSE connection doesn't get timed out by proxies.
                yield TaskStreamEvent(
                    cursor="",
                    seq=0,
                    type="ping",
                    data={},
                )
                continue
            for e in new_events:
                yield e
                cursor = e.cursor
                if e.type in ("done", "error"):
                    return

