from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.doable_claw_agent import router as agent_router
from app.doable_claw_agent.stores import append_message, create_new_conversation, get_conversation, get_last_assistant_message, get_plan_run
from app.middleware.auth_context import get_request_user, require_request_user
from app.repositories import chat_repository
from app.services import central_chat_service
from app.services import payment_entitlement_service
from app.services.messages_service import get_initial_message, handle_send_message_for_problem_identifier_agent, \
    handle_send_message_for_research_agent

router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])


async def _enforce_agent_access(request: Request, agent_id: str) -> None:
    """
    Raise 403 if the agent requires a paid plan and the user doesn't have one.
    Only blocks restricted agents (e.g. research-orchestrator); free agents pass through.
    """
    if not agent_id:
        return
    required_cap = payment_entitlement_service.AGENT_REQUIRED_CAPABILITY.get(agent_id)
    if not required_cap:
        return  # Agent is free

    user = get_request_user(request)
    uid = str(user.get("id") or "").strip() if user else ""
    access = await payment_entitlement_service.check_agent_access(
        user_id=uid, agent_id=agent_id,
    )
    if not access.get("allowed"):
        detail = {
            "error": access.get("reason", "Paid plan required"),
            "code": "AGENT_ACCESS_DENIED",
            "agent_id": agent_id,
        }
        if access.get("required_plan_slug"):
            detail["required_plan_slug"] = access["required_plan_slug"]
        if access.get("required_plan_name"):
            detail["required_plan_name"] = access["required_plan_name"]
        if access.get("required_plan_price"):
            detail["required_plan_price"] = access["required_plan_price"]
        raise HTTPException(status_code=403, detail=detail)


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

    conversation_id = str(body.get("conversationId") or "").strip()
    agent_id_from_body = str(body.get("agentId") or "").strip()

    if not conversation_id:
        if not agent_id_from_body:
            raise HTTPException(status_code=400, detail="conversationId or agentId is required")
        await _enforce_agent_access(req, agent_id_from_body)
        user = get_request_user(req)
        user_id = str(user.get("id") or "").strip() if user else None

        conv = await create_new_conversation(agent_id_from_body, onboarding_id=None, user_id=user_id)
        conversation_id = conv["id"]

        initial = await get_initial_message(agent_id_from_body, user_id=user_id)

        if initial:
            await append_message(
                conversation_id, "assistant", initial["content"],
                options=initial.get("options"), kind=initial.get("kind"),
                allowCustomAnswer=initial.get("allowCustomAnswer", True),
                journeyStep=initial.get("journeyStep"),
                journeySelections=initial.get("journeySelections", {}),
            )
        body["conversationId"] = conversation_id
        req._json = body  # keep req.json() cache in sync for downstream callers

    conversation = await get_conversation(conversation_id, include_messages=False)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    agent_id = str(conversation.get("agentId") or "").strip()
    await _enforce_agent_access(req, agent_id)

    last_assistant_message = await get_last_assistant_message(conversation_id)

    # ── Agent-specific interception ──
    if agent_id == "business_problem_identifier":
        result = await handle_send_message_for_problem_identifier_agent(
            body, conversation, last_assistant_message
        )
        if result is not None:
            return result
    elif agent_id == "research-orchestrator":
        matched = await _match_pending_option(body)
        result = await handle_send_message_for_research_agent(
            body, conversation, last_assistant_message, matched
        )
        if result is not None:
            return result

    if agent_id:
        return await agent_router.agent_message(req)
    try:
        return await central_chat_service.run_message(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/stream")
async def send_message_stream(req: Request) -> StreamingResponse:
    body = await req.json()

    conversation_id = str(body.get("conversationId") or "").strip()
    agent_id = str(body.get("agentId") or "").strip()

    if not conversation_id and agent_id:
        await _enforce_agent_access(req, agent_id)

    if agent_id:
        return await agent_router.agent_chat_plan_stream(req)

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


@router.get("/plan-status")
async def plan_status(plan_id: str = Query(..., alias="planId")) -> dict[str, Any]:
    row = await get_plan_run(plan_id.strip())
    if not row:
        raise HTTPException(status_code=404, detail="plan not found")
    result: dict[str, Any] = {
        "planId": plan_id.strip(),
        "status": row.get("status"),
        "runningTaskRefFound": agent_router.is_plan_background_task_running(plan_id.strip()),
    }
    if row.get("errorMessage"):
        result["errorMessage"] = row.get("errorMessage")
    return result

@router.get("/initial-message")
async def initial_message(req: Request, agentId: str = Query(...)) -> dict[str, Any]:
    agent_id = agentId.strip()
    await _enforce_agent_access(req, agent_id)
    user = get_request_user(req)
    user_id = str(user.get("id") or "").strip() if user else None
    message = await get_initial_message(agent_id, user_id=user_id)
    return {"agentId": agent_id, "message": message}


@router.post("/conversations")
async def create_conversation(req: Request) -> dict[str, Any]:
    body = await req.json()
    agent_id = str(body.get("agentId") or "").strip() or None
    session_id = str(body.get("sessionId") or "").strip() or None
    onboarding_session_id = str(body.get("onboardingSessionId") or "").strip() or session_id
    user_id = str(body.get("userId") or "").strip() or None

    if not agent_id:
        raise HTTPException(status_code=400, detail="agentId is required")

    await _enforce_agent_access(req, agent_id)

    conv = await create_new_conversation(agent_id, onboarding_id=onboarding_session_id, user_id=user_id)
    conversation_id = conv["id"]

    initial = await get_initial_message(agent_id, user_id=user_id)
    if initial and not conv.get("messages"):
        await append_message(
            conversation_id,
            "assistant",
            initial["content"],
            options=initial.get("options"),
            kind=initial.get("kind"),
            allowCustomAnswer=initial.get("allowCustomAnswer", True),
            journeyStep=initial.get("journeyStep"),
            journeySelections=initial.get("journeySelections", {}),
        )
        conv = await get_conversation(conversation_id) or conv

    return {
        "conversationId": conversation_id,
        "agentId": agent_id,
        "onboardingSessionId": onboarding_session_id,
        "messages": conv.get("messages") or [],
    }


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


@router.get("/playbook-history")
async def get_playbook_history(
    userId: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await chat_repository.get_playbook_history(userId, limit, offset)


@router.get("/playbook-runs/{run_id}")
async def get_playbook_run(request: Request, run_id: str) -> dict[str, Any]:
    """Return saved playbook markdown + sections for the authenticated owner."""
    user = require_request_user(request)
    uid = str(user.get("id") or "").strip()
    row = await chat_repository.get_playbook_run_for_user(run_id, uid)
    if not row:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return row


@router.get("/skills")
async def get_skills() -> list[dict[str, Any]]:
    """Returns a JSON array of skill metadata (matches frontend `fetchSkills()`)."""
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


@router.get("/agent-access")
async def check_agent_access(req: Request, agentId: str = Query(...)) -> dict[str, Any]:
    """
    Check if the authenticated user has access to the given agent.
    Returns {"allowed": true} or {"allowed": false, "reason": "...", ...plan details}.
    """
    user = get_request_user(req)
    uid = str(user.get("id") or "").strip() if user else ""
    return await payment_entitlement_service.check_agent_access(
        user_id=uid, agent_id=agentId.strip(),
    )
