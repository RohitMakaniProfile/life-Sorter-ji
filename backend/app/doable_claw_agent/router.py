from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.config import STORAGE_BUCKET
from app.services import unified_chat_service
from app.services.agent_checklist_service import (
    actor_from_payload as _actor_from_payload,
    is_execution_intent as _is_execution_intent,
    is_checklist_task_running as is_plan_background_task_running,
    create_plan_draft,
    prepare_plan_approval as _prepare_plan_approval,
    schedule_plan_approval_background,
    ensure_plan_approval_background,
    execute_plan_approval_work,
)
from .stores import append_assistant_placeholder


router = APIRouter()


def _log(label: str, **fields: Any) -> None:
    try:
        print(f"[doable_claw_agent.router] {label} | {json.dumps(fields, default=str, ensure_ascii=False)}")
    except Exception:
        print(f"[doable_claw_agent.router] {label} | <log-serialize-error>")


def _allowed_file_path(path: str) -> bool:
    if ".." in path:
        return False
    allowed = [Path("/tmp").resolve(), Path(STORAGE_BUCKET).resolve()]
    p = Path(path).resolve()
    for root in allowed:
        if p == root or str(p).startswith(str(root) + "/"):
            return True
    return False


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sse(data: dict[str, Any]) -> bytes:
    try:
        return f"data: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n".encode("utf-8")
    except Exception as exc:
        _log(
            "sse-serialize-failed",
            error=str(exc),
            data_type=type(data).__name__,
            data_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        raise


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api/files/download")
async def agent_files_download(path: str = Query(...)) -> FileResponse:
    if not _allowed_file_path(path):
        raise HTTPException(status_code=403, detail="Access denied")
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = "audio/mpeg" if p.name.endswith(".mp3") else "video/mp4"
    return FileResponse(str(p), media_type=media, filename=p.name)


async def agent_message(req: Request) -> dict[str, Any]:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    session_id, user_id = _actor_from_payload(body)
    # No agent selected => phase1-style normal chat flow.
    if not str(body.get("agentId") or "").strip():
        out = await unified_chat_service.run_standard_chat(
            message=message,
            persona=str(body.get("persona") or "default"),
            context=body.get("context") if isinstance(body.get("context"), dict) else None,
            conversation_history=body.get("conversationHistory") if isinstance(body.get("conversationHistory"), list) else None,
            conversation_id=str(body.get("conversationId") or "").strip() or None,
            session_id=session_id,
            user_id=user_id,
        )
        return {
            "message": out["message"],
            "conversationId": out["conversationId"],
            "mode": "standard",
            "usage": out.get("usage"),
            "stageOutputs": {},
            "outputFile": None,
        }

    # Agent selected, but prompt is regular conversation => use normal LLM chat.
    if not _is_execution_intent(message):
        out = await unified_chat_service.run_standard_chat(
            message=message,
            persona=str(body.get("persona") or "default"),
            context=body.get("context") if isinstance(body.get("context"), dict) else None,
            conversation_history=body.get("conversationHistory") if isinstance(body.get("conversationHistory"), list) else None,
            conversation_id=str(body.get("conversationId") or "").strip() or None,
            session_id=session_id,
            user_id=user_id,
        )
        return {
            "message": out["message"],
            "conversationId": out["conversationId"],
            "mode": "standard",
            "usage": out.get("usage"),
            "stageOutputs": {},
            "outputFile": None,
        }

    # Agent selected + execution intent => plan-first flow, execution happens only after approval.
    draft = await create_plan_draft(body=body)
    return {
        "mode": "agentic-plan",
        "conversationId": draft["conversationId"],
        "planId": draft["planId"],
        "planMessageId": draft["planMessageId"],
        "planMarkdown": draft["planMarkdown"],
    }


async def agent_chat_plan_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    if not str(body.get("agentId") or "").strip():
        raise HTTPException(status_code=400, detail="agentId is required for plan mode")

    if not _is_execution_intent(message):
        session_id, user_id = _actor_from_payload(body)

        async def standard_generator():
            try:
                out = await unified_chat_service.run_standard_chat(
                    message=message,
                    persona=str(body.get("persona") or "default"),
                    context=body.get("context") if isinstance(body.get("context"), dict) else None,
                    conversation_history=body.get("conversationHistory") if isinstance(body.get("conversationHistory"), list) else None,
                    conversation_id=str(body.get("conversationId") or "").strip() or None,
                    session_id=session_id,
                    user_id=user_id,
                )
                yield _sse({"token": out["message"]})
                yield _sse(
                    {
                        "done": True,
                        "mode": "standard",
                        "conversationId": out["conversationId"],
                        "usage": out.get("usage"),
                        "stageOutputs": {},
                        "outputFile": None,
                    }
                )
            except Exception as exc:
                yield _sse({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})

        return StreamingResponse(standard_generator(), media_type="text/event-stream")

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                _log("plan-stream-worker-start")
                await emit({"stage": "thinking", "label": "Building plan", "stageIndex": 0})
                result = await create_plan_draft(body=body, emit_progress=emit_progress, emit_token=emit)
                _log("plan-stream-worker-done", plan_id=result.get("planId"), conversation_id=result.get("conversationId"))
                await emit({
                    "done": True,
                    "conversationId": result.get("conversationId"),
                    "planId": result.get("planId"),
                    "planMessageId": result.get("planMessageId"),
                    "planMarkdown": result.get("planMarkdown"),
                    "agentId": result.get("agentId"),
                    "skillId": result.get("skillId"),
                })
            except Exception as exc:
                import traceback
                _log("plan-stream-worker-error", error=str(exc), traceback=traceback.format_exc())
                await emit({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


async def _approve_plan_stream_body(body: dict[str, Any]) -> StreamingResponse:
    conv, plan, resolved, plan_id, session_id = await _prepare_plan_approval(body)
    assistant_message_id = await append_assistant_placeholder(conv["id"])

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                await execute_plan_approval_work(
                    plan_id=plan_id,
                    conv=conv,
                    plan=plan,
                    resolved=resolved,
                    assistant_message_id=assistant_message_id,
                    session_id=session_id,
                    emit=emit,
                    emit_progress=emit_progress,
                )
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")