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
        import structlog
        logger = structlog.get_logger()

        logger.info("task_stream_service_start",
                   task_type=task_type,
                   onboarding_id=onboarding_id,
                   user_id=user_id,
                   resume_if_exists=resume_if_exists,
                   force_fresh=force_fresh)

        if not (onboarding_id or user_id):
            logger.error("task_stream_no_actor")
            raise HTTPException(status_code=400, detail="Provide onboarding_id or user_id")

        # Force fresh: mark any existing streams as cancelled/stale before starting new
        if force_fresh:
            logger.info("task_stream_force_fresh_checking")
            existing = await self.store.resolve_stream_id(
                task_type, onboarding_id=onboarding_id, user_id=user_id
            )
            if existing:
                logger.info("task_stream_found_existing", stream_id=existing)
                old_status = await self.store.get_status(existing)
                # Mark as cancelled if it was running (stale)
                if old_status == "running":
                    logger.info("task_stream_cancelling_old", stream_id=existing)
                    await self.store.set_status(existing, "cancelled")
                    await self.store.xadd_event(existing, "error", {"message": "Superseded by new task"})
                # Clear the actor mapping so we start fresh
                await self.store.clear_actor_mapping(task_type, onboarding_id=onboarding_id, user_id=user_id)

        # 1) Resume by mapping (onboarding_id/user_id) if desired.
        #    Resume 'running' streams (live attach) and 'done' streams (replay final event).
        #    Do NOT resume 'error' or 'cancelled' — those should restart fresh.
        if resume_if_exists and not force_fresh:
            logger.info("task_stream_checking_resume")
            existing = await self.store.resolve_stream_id(
                task_type, onboarding_id=onboarding_id, user_id=user_id
            )
            if existing:
                status = await self.store.get_status(existing)
                logger.info("task_stream_found_existing_for_resume", stream_id=existing, status=status)
                if status in ("running", "done"):
                    return {"stream_id": existing, "status": status}

        # 2) Acquire a lightweight lock so concurrent start requests don't double-spawn.
        actor_key = (onboarding_id or "").strip() or (user_id or "").strip() or "anon"
        lock_key = f"{REDIS_TASKSTREAM_PREFIX}:lock:{task_type}:{actor_key}"
        logger.info("task_stream_acquiring_lock", lock_key=lock_key)

        acquired = False
        try:
            acquired = await self.store.try_acquire_spawn_lock(lock_key)
            logger.info("task_stream_lock_acquired", acquired=acquired)

            if not acquired:
                logger.warning("task_stream_lock_contention", lock_key=lock_key)
                for i in range(20):
                    await asyncio.sleep(0.1)
                    existing = await self.store.resolve_stream_id(
                        task_type, onboarding_id=onboarding_id, user_id=user_id
                    )
                    if existing:
                        status = await self.store.get_status(existing)
                        if status == "running":
                            logger.info("task_stream_lock_wait_found_stream", stream_id=existing)
                            return {"stream_id": existing, "status": status}
                logger.error("task_stream_lock_timeout")
                raise HTTPException(status_code=409, detail="Task stream start contention")

            # 3) Create new stream and meta.
            stream_id = str(uuid.uuid4())
            logger.info("task_stream_creating", stream_id=stream_id)

            await self.store.create_stream_and_meta(
                stream_id,
                task_type=task_type,
                onboarding_id=onboarding_id,
                user_id=user_id,
                status="running",
            )
            logger.info("task_stream_created", stream_id=stream_id)

            await self.store.set_actor_mapping(
                task_type,
                stream_id=stream_id,
                onboarding_id=onboarding_id,
                user_id=user_id,
            )
            logger.info("task_stream_mapped", stream_id=stream_id)

            task_payload: dict[str, Any] = {**payload}
            if onboarding_id:
                task_payload.setdefault("onboarding_id", onboarding_id)
            if user_id:
                task_payload.setdefault("user_id", user_id)

            async def send(event_type: str, **data: Any) -> None:
                await self.store.xadd_event(stream_id, event_type, data)

            async def _runner() -> None:
                try:
                    logger.info("task_stream_runner_starting", stream_id=stream_id)
                    done_data = await task_fn(send, task_payload)
                    await self.store.set_status(stream_id, "done")
                    if done_data is None:
                        done_data = {"result": task_payload}
                    await send("done", **done_data)
                    logger.info("task_stream_runner_done", stream_id=stream_id)
                except asyncio.CancelledError:
                    logger.warning("task_stream_runner_cancelled", stream_id=stream_id)
                    await self.store.set_status(stream_id, "cancelled")
                    await send("error", message="Task cancelled")
                except Exception as exc:
                    logger.error("task_stream_runner_error",
                               stream_id=stream_id,
                               error=str(exc),
                               error_type=type(exc).__name__)
                    await self.store.set_status(stream_id, "error")
                    await send("error", message=str(exc))

            asyncio.create_task(_runner())
            logger.info("task_stream_runner_spawned", stream_id=stream_id)
            return {"stream_id": stream_id, "status": "running"}
        except Exception as e:
            logger.error("task_stream_service_exception",
                        error=str(e),
                        error_type=type(e).__name__,
                        task_type=task_type)
            raise
        finally:
            if acquired:
                logger.info("task_stream_releasing_lock", lock_key=lock_key)
                await self.store.release_spawn_lock(lock_key)

