from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.phase2 import router as phase2_router
from app.phase2.stores import append_message, get_conversation, update_plan_run
from app.repositories import chat_repository
from app.services import central_chat_service

router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sse(data: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n".encode("utf-8")


def _normalize_option(value: str) -> str:
    return value.strip().lower()


async def _match_pending_option(body: dict[str, Any]) -> tuple[dict[str, Any], str, bool] | None:
    conversation_id = str(body.get("conversationId") or "").strip()
    incoming = str(body.get("message") or "").strip()
    if not conversation_id or not incoming:
        return None

    conv = await get_conversation(conversation_id)
    if not conv:
        return None
    messages = conv.get("messages") or []
    if not messages:
        return None

    incoming_norm = _normalize_option(incoming)
    candidates: list[tuple[dict[str, Any], bool]] = []
    if messages[-1].get("role") == "assistant":
        candidates.append((messages[-1], False))
    if len(messages) >= 2 and messages[-1].get("role") == "user" and messages[-2].get("role") == "assistant":
        candidates.append((messages[-2], True))

    for assistant_msg, already_logged in candidates:
        options = assistant_msg.get("options")
        if not isinstance(options, list) or not options:
            continue
        for option in options:
            if not isinstance(option, str):
                continue
            option_norm = _normalize_option(option)
            if option_norm != incoming_norm:
                continue
            if already_logged and _normalize_option(str(messages[-1].get("content") or "")) != incoming_norm:
                continue
            return assistant_msg, option, already_logged
    return None


@router.post("/message")
async def send_message(req: Request) -> dict[str, Any]:
    body = await req.json()
    matched = await _match_pending_option(body)
    if matched:
        last_assistant, selected, already_logged = matched
        conversation_id = str(body.get("conversationId") or "").strip()
        if not already_logged:
            await append_message(conversation_id, "user", selected)
        plan_id = str(last_assistant.get("planId") or "").strip() or None
        lower = _normalize_option(selected)
        if lower == "cancel":
            if plan_id:
                await update_plan_run(plan_id, {"status": "cancelled"})
            await append_message(conversation_id, "assistant", "Plan cancelled.", kind="final")
            return {
                "mode": "option",
                "conversationId": conversation_id,
                "optionSelected": selected,
                "status": "cancelled",
            }
        return {
            "mode": "option",
            "conversationId": conversation_id,
            "optionSelected": selected,
            "status": "accepted",
            "planId": plan_id,
            "requiresStream": lower == "approve",
        }

    if str(body.get("agentId") or "").strip():
        return await phase2_router.p2_chat_message(req)
    try:
        return await central_chat_service.run_message(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stream")
async def send_message_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    matched = await _match_pending_option(body)
    if matched:
        last_assistant, selected, already_logged = matched
        conversation_id = str(body.get("conversationId") or "").strip()
        if not already_logged:
            await append_message(conversation_id, "user", selected)
        lower = _normalize_option(selected)
        if lower == "approve" and str(body.get("agentId") or "").strip():
            plan_id = str(last_assistant.get("planId") or "").strip()
            if not plan_id:
                raise HTTPException(status_code=400, detail="No pending plan found to approve")
            approve_body = {
                "planId": plan_id,
                "conversationId": conversation_id,
                "planMarkdown": str(last_assistant.get("content") or ""),
                "agentId": body.get("agentId"),
                "sessionId": body.get("sessionId"),
                "userId": body.get("userId"),
            }
            return await phase2_router._approve_plan_stream_body(approve_body)
        if lower == "cancel":
            plan_id = str(last_assistant.get("planId") or "").strip()
            if plan_id:
                await update_plan_run(plan_id, {"status": "cancelled"})
            await append_message(conversation_id, "assistant", "Plan cancelled.", kind="final")

            async def cancel_generator():
                yield _sse({"token": "Plan cancelled."})
                yield _sse({"done": True, "conversationId": conversation_id, "mode": "option", "optionSelected": selected})

            return StreamingResponse(cancel_generator(), media_type="text/event-stream")

    if str(body.get("agentId") or "").strip():
        return await phase2_router.p2_chat_plan_stream(req)

    async def generator():
        try:
            async for event in central_chat_service.run_stream(body):
                if event.get("ping"):
                    yield b": ping\n\n"
                else:
                    yield _sse(event)
        except ValueError as exc:
            yield _sse({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
        except Exception as exc:  # pragma: no cover
            yield _sse({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/messages")
async def get_messages(
    conversationId: str | None = None,
    sessionId: str | None = Query(default=None),
    userId: str | None = Query(default=None),
) -> dict[str, Any]:
    return await chat_repository.get_messages(conversationId, sessionId, userId)


@router.get("/conversations")
async def get_conversations(
    sessionId: str | None = Query(default=None),
    userId: str | None = Query(default=None),
) -> dict[str, Any]:
    return await chat_repository.get_conversations(sessionId, userId)


@router.get("/skills")
async def get_skills() -> dict[str, Any]:
    return await chat_repository.get_skills()


@router.get("/skill-calls")
async def get_skill_calls(messageId: str | None = None) -> dict[str, Any]:
    try:
        return await chat_repository.get_skill_calls(messageId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/token-usage")
async def get_token_usage(messageId: str | None = None) -> dict[str, Any]:
    try:
        return await chat_repository.get_token_usage_by_message(messageId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    return await chat_repository.delete_conversation_by_id(conversation_id)

