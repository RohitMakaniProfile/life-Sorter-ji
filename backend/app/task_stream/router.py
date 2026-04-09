from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Body, HTTPException, Header
from fastapi.responses import StreamingResponse

from app.services.jwt_service import decode_and_verify_access_token
from app.task_stream.models import TaskStreamStartRequest
from app.task_stream.service import TaskFn, TaskStreamService


def create_task_stream_router(
    *,
    service: TaskStreamService,
    task_registry: dict[str, TaskFn],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/task-stream", tags=["TaskStream"])

    _DEFAULT_HEADERS: dict[str, str] = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }

    def _actor_from_auth(authorization: str | None) -> tuple[str | None, str | None]:
        raw = (authorization or "").strip()
        if not raw.lower().startswith("bearer "):
            return None, None
        token = raw[7:].strip()
        if not token:
            return None, None
        try:
            payload = decode_and_verify_access_token(token)
        except Exception:
            return None, None
        user_id = str(payload.get("sub") or "").strip() or None
        onboarding_id = (
            str(payload.get("onboarding_session_id") or payload.get("onboarding_id") or "").strip() or None
        )
        return onboarding_id, user_id

    @router.post("/start/{task_type:path}")
    async def start_task_stream(
        task_type: str,
        body: TaskStreamStartRequest = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        task_fn = task_registry.get(task_type)
        if not task_fn:
            raise HTTPException(status_code=404, detail=f"Unknown task_type: {task_type}")
        auth_oid, auth_uid = _actor_from_auth(authorization)
        eff_onboarding_id = body.onboarding_id or auth_oid
        eff_user_id = body.user_id or auth_uid

        return await service.start_task_stream(
            task_type=task_type,
            task_fn=task_fn,
            payload=body.payload or {},
            onboarding_id=eff_onboarding_id,
            user_id=eff_user_id,
            resume_if_exists=body.resume_if_exists,
            force_fresh=body.force_fresh,
        )

    @router.get("/events/{stream_id}")
    async def attach_stream(stream_id: str, cursor: str | None = None) -> StreamingResponse:
        status = await service.store.get_status(stream_id)
        if not status:
            raise HTTPException(status_code=404, detail="Unknown stream_id")

        # StreamingResponse needs an async generator; build it on-demand.
        async def event_generator():
            # iter_events already does backlog-on-first-connect.
            async for e in service.store.iter_events(stream_id, cursor=cursor):
                payload = {"stream_id": stream_id, "type": e.type, **e.data, "cursor": e.cursor}
                yield f"data: {json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=_DEFAULT_HEADERS,
        )

    @router.get("/events/{task_type:path}/resume")
    async def resume_by_actor(
        task_type: str,
        onboarding_id: str | None = None,
        user_id: str | None = None,
        cursor: str | None = None,
    ) -> StreamingResponse:
        stream_id = await service.store.resolve_stream_id(
            task_type, onboarding_id=onboarding_id, user_id=user_id
        )
        if not stream_id:
            raise HTTPException(status_code=404, detail="No active task stream found for actor")

        status = await service.store.get_status(stream_id)
        if not status:
            raise HTTPException(status_code=404, detail="Unknown stream_id")

        async def event_generator():
            async for e in service.store.iter_events(stream_id, cursor=cursor):
                payload = {"stream_id": stream_id, "type": e.type, **e.data, "cursor": e.cursor}
                yield f"data: {json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=_DEFAULT_HEADERS,
        )

    @router.get("/status/{stream_id}")
    async def stream_status(stream_id: str) -> dict[str, Any]:
        status = await service.store.get_status(stream_id)
        if not status:
            raise HTTPException(status_code=404, detail="Unknown stream_id")
        return await service.store.get_meta(stream_id)

    # Lightweight demo task (useful for smoke-testing the infrastructure).
    # It can be removed once you wire real tasks.
    async def _demo_task(send: Callable[..., Awaitable[None]], payload: dict[str, Any]) -> dict[str, Any]:
        message = str(payload.get("message") or "hello from task-stream demo")
        await send("stage", stage="running", label="Task-stream demo running")
        # Emit a couple of incremental updates.
        for w in message.split():
            await send("token", token=w + " ")
            await asyncio.sleep(0.05)
        return {"result": message.strip()}

    # If caller didn't register demo, register it automatically for convenience.
    # This does not start anything; it just enables the endpoint to resolve a task_type.
    if "task-stream-demo" not in task_registry:
        task_registry["task-stream-demo"] = _demo_task  # type: ignore[assignment]

    return router

