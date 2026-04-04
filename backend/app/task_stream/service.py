from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException

from app.config import REDIS_TASKSTREAM_PREFIX
from app.task_stream.store_factory import get_task_stream_store


TaskStreamSender = Callable[..., Awaitable[None]]
TaskFn = Callable[[TaskStreamSender, dict[str, Any]], Awaitable[Optional[dict[str, Any]]]]


class TaskStreamService:
    """
    Orchestrates background execution + durable task-stream persistence.

    Background tasks run in the same Python process (asyncio task), but
    progress is persisted (Redis Streams or Postgres; see TASKSTREAM_BACKEND)
    so clients can re-attach after refresh.
    """

    def __init__(self, store: Optional[object] = None) -> None:
        self.store = store or get_task_stream_store()

    async def start_task_stream(
        self,
        *,
        task_type: str,
        task_fn: TaskFn,
        payload: dict[str, Any],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        resume_if_exists: bool = True,
    ) -> dict[str, str]:
        if not (session_id or user_id):
            raise HTTPException(status_code=400, detail="Provide session_id or user_id")

        # 1) Resume by mapping (session_id/user_id) if desired.
        #    Only resume if the stream is still running; ignore done/error/cancelled streams.
        if resume_if_exists:
            existing = await self.store.resolve_stream_id(
                task_type, session_id=session_id, user_id=user_id
            )
            if existing:
                status = await self.store.get_status(existing)
                if status == "running":
                    return {"stream_id": existing, "status": status}

        # 2) Acquire a lightweight lock so concurrent start requests don't double-spawn.
        actor_key = (session_id or "").strip() or (user_id or "").strip() or "anon"
        lock_key = f"{REDIS_TASKSTREAM_PREFIX}:lock:{task_type}:{actor_key}"
        acquired = False
        try:
            acquired = await self.store.try_acquire_spawn_lock(lock_key)
            if not acquired:
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    existing = await self.store.resolve_stream_id(
                        task_type, session_id=session_id, user_id=user_id
                    )
                    if existing:
                        status = await self.store.get_status(existing)
                        if status == "running":
                            return {"stream_id": existing, "status": status}
                raise HTTPException(status_code=409, detail="Task stream start contention")

            # 3) Create new stream and meta.
            stream_id = str(uuid.uuid4())
            await self.store.create_stream_and_meta(
                stream_id,
                task_type=task_type,
                session_id=session_id,
                user_id=user_id,
                status="running",
            )
            await self.store.set_actor_mapping(
                task_type,
                stream_id=stream_id,
                session_id=session_id,
                user_id=user_id,
            )

            task_payload: dict[str, Any] = {**payload}
            if session_id:
                task_payload.setdefault("session_id", session_id)
            if user_id:
                task_payload.setdefault("user_id", user_id)

            async def send(event_type: str, **data: Any) -> None:
                await self.store.xadd_event(stream_id, event_type, data)

            async def _runner() -> None:
                try:
                    done_data = await task_fn(send, task_payload)
                    await self.store.set_status(stream_id, "done")
                    if done_data is None:
                        done_data = {"result": task_payload}
                    await send("done", **done_data)
                except asyncio.CancelledError:
                    await self.store.set_status(stream_id, "cancelled")
                    await send("error", message="Task cancelled")
                except Exception as exc:
                    await self.store.set_status(stream_id, "error")
                    await send("error", message=str(exc))

            asyncio.create_task(_runner())
            return {"stream_id": stream_id, "status": "running"}
        finally:
            if acquired:
                await self.store.release_spawn_lock(lock_key)

