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
        onboarding_id: Optional[str] = None,
        user_id: Optional[str] = None,
        resume_if_exists: bool = True,
        force_fresh: bool = False,
    ) -> dict[str, str]:
        if not (onboarding_id or user_id):
            raise HTTPException(status_code=400, detail="Provide onboarding_id or user_id")

        # Force fresh: mark any existing streams as cancelled/stale before starting new
        if force_fresh:
            existing = await self.store.resolve_stream_id(
                task_type, onboarding_id=onboarding_id, user_id=user_id
            )
            if existing:
                old_status = await self.store.get_status(existing)
                # Mark as cancelled if it was running (stale)
                if old_status == "running":
                    await self.store.set_status(existing, "cancelled")
                    await self.store.xadd_event(existing, "error", {"message": "Superseded by new task"})
                # Clear the actor mapping so we start fresh
                await self.store.clear_actor_mapping(task_type, onboarding_id=onboarding_id, user_id=user_id)

        # 1) Resume by mapping (onboarding_id/user_id) if desired.
        #    Resume 'running' streams (live attach) and 'done' streams (replay final event).
        #    Do NOT resume 'error' or 'cancelled' — those should restart fresh.
        if resume_if_exists and not force_fresh:
            existing = await self.store.resolve_stream_id(
                task_type, onboarding_id=onboarding_id, user_id=user_id
            )
            if existing:
                status = await self.store.get_status(existing)
                if status in ("running", "done"):
                    return {"stream_id": existing, "status": status}

        # 2) Acquire a lightweight lock so concurrent start requests don't double-spawn.
        actor_key = (onboarding_id or "").strip() or (user_id or "").strip() or "anon"
        lock_key = f"{REDIS_TASKSTREAM_PREFIX}:lock:{task_type}:{actor_key}"
        acquired = False
        try:
            acquired = await self.store.try_acquire_spawn_lock(lock_key)
            if not acquired:
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    existing = await self.store.resolve_stream_id(
                        task_type, onboarding_id=onboarding_id, user_id=user_id
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
                onboarding_id=onboarding_id,
                user_id=user_id,
                status="running",
            )
            await self.store.set_actor_mapping(
                task_type,
                stream_id=stream_id,
                onboarding_id=onboarding_id,
                user_id=user_id,
            )

            task_payload: dict[str, Any] = {**payload}
            if onboarding_id:
                task_payload.setdefault("onboarding_id", onboarding_id)
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

