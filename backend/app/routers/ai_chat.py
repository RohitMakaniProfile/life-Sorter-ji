from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.doable_claw_agent import router as agent_router
from app.doable_claw_agent.stores import append_message, create_new_conversation, get_conversation, get_or_create_conversation, get_plan_run, update_plan_run
from app.middleware.auth_context import get_request_user
from app.services import journey_service
from app.repositories import chat_repository
from app.services import central_chat_service
from app.services import payment_entitlement_service

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

    # ── Plan access check for new conversations with restricted agents ──
    conversation_id_check = str(body.get("conversationId") or "").strip()
    agent_id_check = str(body.get("agentId") or "").strip()
    if not conversation_id_check and agent_id_check:
        # No existing conversation → creating new one; enforce plan check
        await _enforce_agent_access(req, agent_id_check)

    matched = await _match_pending_option(body)
    if matched:
        last_assistant, selected, already_logged = matched
        conversation_id = str(body.get("conversationId") or "").strip()
        if not already_logged:
            await append_message(conversation_id, "user", selected)

        # ── Journey step handling for business_problem_identifier ──────────
        journey_step = str(last_assistant.get("journeyStep") or "").strip()
        if journey_step:
            journey_selections = last_assistant.get("journeySelections") or {}
            next_msg = await journey_service.next_step(journey_step, selected, journey_selections)
            if next_msg is not None:
                await append_message(
                    conversation_id,
                    "assistant",
                    next_msg["content"],
                    options=next_msg["options"],
                    allowCustomAnswer=next_msg["allowCustomAnswer"],
                    journeyStep=next_msg["journeyStep"],
                    journeySelections=next_msg.get("journeySelections", {}),
                    kind="final",
                )
                conv = await get_conversation(conversation_id) or {}
                return {
                    "mode": "journey",
                    "conversationId": conversation_id,
                    "optionSelected": selected,
                    "journeyStep": next_msg["journeyStep"],
                    "messages": conv.get("messages") or [],
                }
        # ──────────────────────────────────────────────────────────────────

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
        if lower == "approve" and str(body.get("agentId") or "").strip() and plan_id:
            approve_body = {
                "planId": plan_id,
                "conversationId": conversation_id,
                "planMarkdown": str(last_assistant.get("content") or ""),
                "agentId": body.get("agentId"),
                "sessionId": body.get("sessionId"),
                "userId": body.get("userId"),
            }
            # Start plan execution via task stream (replaces background execution + polling)
            task_stream_result = await agent_router.start_plan_via_task_stream(approve_body)
            return {
                "mode": "option",
                "conversationId": conversation_id,
                "optionSelected": selected,
                "status": "accepted",
                "planId": plan_id,
                "requiresStream": False,
                "backgroundExecution": True,
                "taskStream": {
                    "streamId": task_stream_result.get("streamId"),
                    "taskType": "plan/execute",
                },
                **{k: v for k, v in task_stream_result.items() if k not in ("streamId", "useTaskStream")},
            }
        return {
            "mode": "option",
            "conversationId": conversation_id,
            "optionSelected": selected,
            "status": "accepted",
            "planId": plan_id,
            "requiresStream": False,
        }

    # ── Resolve effective agentId from conversation (body agentId may be wrong) ──
    agent_id_raw = str(body.get("agentId") or "").strip()
    conversation_id_ft = str(body.get("conversationId") or "").strip()
    effective_agent_id = agent_id_raw
    _conv_for_journey: dict[str, Any] | None = None

    if conversation_id_ft:
        _conv_for_journey = await get_conversation(conversation_id_ft)
        if _conv_for_journey:
            conv_agent_id = str(_conv_for_journey.get("agentId") or "").strip()
            # Always prefer the conversation's stored agentId over the body
            if conv_agent_id:
                effective_agent_id = conv_agent_id

    # ── Intercept free-text for business_problem_identifier journey steps ──
    if effective_agent_id == "business_problem_identifier" and conversation_id_ft:
        conv = _conv_for_journey
        if conv:
            msgs = conv.get("messages") or []
            last_asst = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
            if last_asst:
                step = str(last_asst.get("journeyStep") or "").strip()
                user_text = str(body.get("message") or "").strip()
                prev_selections = last_asst.get("journeySelections") or {}

                # URL free-text (enter website URL or type anything non-Skip)
                if step == journey_service.JOURNEY_STEP_URL and user_text:
                    await append_message(conversation_id_ft, "user", user_text)
                    next_msg = journey_service.start_scale_questions(url=user_text, acc=prev_selections)
                    await append_message(
                        conversation_id_ft,
                        "assistant",
                        next_msg["content"],
                        options=next_msg["options"],
                        allowCustomAnswer=next_msg["allowCustomAnswer"],
                        journeyStep=next_msg["journeyStep"],
                        journeySelections=next_msg.get("journeySelections", {}),
                        kind=next_msg.get("kind", "final"),
                    )
                    conv = await get_conversation(conversation_id_ft) or {}
                    return {
                        "mode": "journey",
                        "conversationId": conversation_id_ft,
                        "journeyStep": next_msg["journeyStep"],
                        "messages": conv.get("messages") or [],
                    }

                # Playbook retry: any message restarts generation
                if step == journey_service.JOURNEY_STEP_PLAYBOOK and user_text:
                    await append_message(conversation_id_ft, "user", user_text)
                    next_msg = await journey_service.next_step(step, user_text, prev_selections)
                    if next_msg is not None:
                        await append_message(
                            conversation_id_ft,
                            "assistant",
                            next_msg["content"],
                            options=next_msg["options"],
                            allowCustomAnswer=next_msg["allowCustomAnswer"],
                            journeyStep=next_msg["journeyStep"],
                            journeySelections=next_msg.get("journeySelections", {}),
                            kind="final",
                        )
                        conv = await get_conversation(conversation_id_ft) or {}
                        return {
                            "mode": "journey",
                            "conversationId": conversation_id_ft,
                            "journeyStep": next_msg["journeyStep"],
                            "messages": conv.get("messages") or [],
                        }

                # Diagnostic / Precision / Gap free-text answers
                _FREE_TEXT_STEPS = {
                    journey_service.JOURNEY_STEP_DIAGNOSTIC,
                    journey_service.JOURNEY_STEP_PRECISION,
                    journey_service.JOURNEY_STEP_GAP,
                }
                if step in _FREE_TEXT_STEPS and user_text and last_asst.get("allowCustomAnswer"):
                    await append_message(conversation_id_ft, "user", user_text)
                    next_msg = await journey_service.next_step(step, user_text, prev_selections)
                    if next_msg is not None:
                        await append_message(
                            conversation_id_ft,
                            "assistant",
                            next_msg["content"],
                            options=next_msg["options"],
                            allowCustomAnswer=next_msg["allowCustomAnswer"],
                            journeyStep=next_msg["journeyStep"],
                            journeySelections=next_msg.get("journeySelections", {}),
                            kind="final",
                        )
                        conv = await get_conversation(conversation_id_ft) or {}
                        return {
                            "mode": "journey",
                            "conversationId": conversation_id_ft,
                            "journeyStep": next_msg["journeyStep"],
                            "messages": conv.get("messages") or [],
                        }
    # ────────────────────────────────────────────────────────────────────────

    if effective_agent_id:
        return await agent_router.agent_message(req)
    try:
        return await central_chat_service.run_message(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/message/background")
async def send_message_background(req: Request) -> dict[str, Any]:
    """
    Start option-based execution in background (durable across frontend refresh).
    Currently used for plan approve path.
    """
    body = await req.json()

    # ── Plan access check: resolve agent from conversation or body ──
    bg_conv_id = str(body.get("conversationId") or "").strip()
    bg_agent_id = str(body.get("agentId") or "").strip()
    if bg_conv_id and not bg_agent_id:
        bg_conv = await get_conversation(bg_conv_id)
        if bg_conv:
            bg_agent_id = str(bg_conv.get("agentId") or "").strip()
    if bg_agent_id:
        await _enforce_agent_access(req, bg_agent_id)

    # Prefer direct approve/cancel by planId when provided.
    msg = _normalize_option(str(body.get("message") or ""))
    plan_id_direct = str(body.get("planId") or "").strip()
    conversation_id_direct = str(body.get("conversationId") or "").strip()

    # Backward-compatible recovery: if planId isn't sent by frontend, resolve the latest
    # pending plan from conversation history.
    if not plan_id_direct and conversation_id_direct and msg in ("approve", "cancel"):
        conv = await get_conversation(conversation_id_direct)
        if conv:
            messages = conv.get("messages") or []
            for m in reversed(messages):
                if not isinstance(m, dict):
                    continue
                if str(m.get("role") or "") != "assistant":
                    continue
                pid = str(m.get("planId") or "").strip()
                if not pid:
                    continue
                opts = m.get("options") if isinstance(m.get("options"), list) else []
                norm_opts = {_normalize_option(str(o)) for o in opts if isinstance(o, str)}
                # Prefer plans that still expose options; otherwise fallback to latest planId.
                if msg in norm_opts:
                    plan_id_direct = pid
                    break
                if not plan_id_direct:
                    plan_id_direct = pid

    if plan_id_direct and conversation_id_direct and msg in ("approve", "cancel"):
        if msg == "cancel":
            await update_plan_run(plan_id_direct, {"status": "cancelled"})
            await append_message(conversation_id_direct, "assistant", "Plan cancelled.", kind="final")
            return {
                "mode": "option",
                "conversationId": conversation_id_direct,
                "optionSelected": "cancel",
                "status": "cancelled",
                "planId": plan_id_direct,
            }
        if not str(body.get("agentId") or "").strip():
            raise HTTPException(status_code=400, detail="agentId is required for approve")
        plan = await get_plan_run(plan_id_direct)
        if not plan:
            raise HTTPException(status_code=404, detail="plan not found")
        approve_body = {
            "planId": plan_id_direct,
            "conversationId": conversation_id_direct,
            "planMarkdown": str(body.get("planMarkdown") or plan.get("planMarkdown") or ""),
            "agentId": body.get("agentId"),
            "sessionId": body.get("sessionId"),
            "userId": body.get("userId"),
        }
        # Start plan execution via task stream (replaces background execution + polling)
        task_stream_result = await agent_router.start_plan_via_task_stream(approve_body)
        return {
            "mode": "option",
            "conversationId": conversation_id_direct,
            "optionSelected": "approve",
            "status": "accepted",
            "planId": plan_id_direct,
            "backgroundExecution": True,
            "taskStream": {
                "streamId": task_stream_result.get("streamId"),
                "taskType": "plan/execute",
            },
            **{k: v for k, v in task_stream_result.items() if k not in ("streamId", "useTaskStream")},
        }

    matched = await _match_pending_option(body)
    if not matched:
        raise HTTPException(status_code=400, detail="No pending option found for background execution")

    last_assistant, selected, already_logged = matched
    conversation_id = str(body.get("conversationId") or "").strip()
    if not already_logged:
        await append_message(conversation_id, "user", selected)

    lower = _normalize_option(selected)
    plan_id = str(last_assistant.get("planId") or "").strip()
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

    if lower != "approve" or not plan_id or not str(body.get("agentId") or "").strip():
        raise HTTPException(status_code=400, detail="Only approve option is supported for /message/background")

    approve_body = {
        "planId": plan_id,
        "conversationId": conversation_id,
        "planMarkdown": str(last_assistant.get("content") or ""),
        "agentId": body.get("agentId"),
        "sessionId": body.get("sessionId"),
        "userId": body.get("userId"),
    }
    # Start plan execution via task stream (replaces background execution + polling)
    task_stream_result = await agent_router.start_plan_via_task_stream(approve_body)
    return {
        "mode": "option",
        "conversationId": conversation_id,
        "optionSelected": selected,
        "status": "accepted",
        "planId": plan_id,
        "backgroundExecution": True,
        "taskStream": {
            "streamId": task_stream_result.get("streamId"),
            "taskType": "plan/execute",
        },
        **{k: v for k, v in task_stream_result.items() if k not in ("streamId", "useTaskStream")},
    }


@router.post("/stream")
async def send_message_stream(req: Request) -> StreamingResponse:
    body = await req.json()

    # ── Plan access check for new conversations with restricted agents ──
    conversation_id_check_s = str(body.get("conversationId") or "").strip()
    agent_id_check_s = str(body.get("agentId") or "").strip()
    if not conversation_id_check_s and agent_id_check_s:
        # No existing conversation → creating new one; enforce plan check
        await _enforce_agent_access(req, agent_id_check_s)

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
            return await agent_router._approve_plan_stream_body(approve_body)
        if lower == "cancel":
            plan_id = str(last_assistant.get("planId") or "").strip()
            if plan_id:
                await update_plan_run(plan_id, {"status": "cancelled"})
            await append_message(conversation_id, "assistant", "Plan cancelled.", kind="final")

            async def cancel_generator():
                yield _sse({"token": "Plan cancelled."})
                yield _sse({"done": True, "conversationId": conversation_id, "mode": "option", "optionSelected": selected})

            return StreamingResponse(cancel_generator(), media_type="text/event-stream")

    # ── Intercept free-text for business_problem_identifier journey steps (stream) ──
    agent_id_stream = str(body.get("agentId") or "").strip()
    conversation_id_s = str(body.get("conversationId") or "").strip()
    # Resolve agentId from conversation table (body may be wrong).
    eff_agent_id_stream = agent_id_stream
    _conv_s_cached: dict[str, Any] | None = None
    if conversation_id_s:
        _conv_s_cached = await get_conversation(conversation_id_s)
        if _conv_s_cached:
            _sid_agent = str(_conv_s_cached.get("agentId") or "").strip()
            if _sid_agent:
                eff_agent_id_stream = _sid_agent
    if eff_agent_id_stream == "business_problem_identifier":
        if conversation_id_s:
            conv_s = _conv_s_cached
            if conv_s:
                msgs_s = conv_s.get("messages") or []
                last_asst_s = next((m for m in reversed(msgs_s) if m.get("role") == "assistant"), None)
                if last_asst_s:
                    step_s = str(last_asst_s.get("journeyStep") or "").strip()
                    user_text_s = str(body.get("message") or "").strip()
                    prev_sel_s = last_asst_s.get("journeySelections") or {}

                    _FREE_TEXT_STEPS_S = {
                        journey_service.JOURNEY_STEP_URL,
                        journey_service.JOURNEY_STEP_DIAGNOSTIC,
                        journey_service.JOURNEY_STEP_PRECISION,
                        journey_service.JOURNEY_STEP_GAP,
                    }
                    if step_s == journey_service.JOURNEY_STEP_PLAYBOOK and user_text_s:
                        await append_message(conversation_id_s, "user", user_text_s)
                        next_msg_s = await journey_service.next_step(step_s, user_text_s, prev_sel_s)

                        if next_msg_s is not None:
                            await append_message(
                                conversation_id_s,
                                "assistant",
                                next_msg_s["content"],
                                options=next_msg_s["options"],
                                allowCustomAnswer=next_msg_s["allowCustomAnswer"],
                                journeyStep=next_msg_s["journeyStep"],
                                journeySelections=next_msg_s.get("journeySelections", {}),
                                kind="final",
                            )
                            next_step_val_pb = next_msg_s["journeyStep"]

                            async def _playbook_retry_gen():
                                yield _sse({"done": True, "conversationId": conversation_id_s, "mode": "journey", "journeyStep": next_step_val_pb})

                            return StreamingResponse(_playbook_retry_gen(), media_type="text/event-stream")
                    elif step_s in _FREE_TEXT_STEPS_S and user_text_s and last_asst_s.get("allowCustomAnswer"):
                        await append_message(conversation_id_s, "user", user_text_s)
                        if step_s == journey_service.JOURNEY_STEP_URL:
                            next_msg_s = journey_service.start_scale_questions(url=user_text_s, acc=prev_sel_s)
                        else:
                            next_msg_s = await journey_service.next_step(step_s, user_text_s, prev_sel_s)

                        if next_msg_s is not None:
                            await append_message(
                                conversation_id_s,
                                "assistant",
                                next_msg_s["content"],
                                options=next_msg_s["options"],
                                allowCustomAnswer=next_msg_s["allowCustomAnswer"],
                                journeyStep=next_msg_s["journeyStep"],
                                journeySelections=next_msg_s.get("journeySelections", {}),
                                kind="final",
                            )
                            next_step_val = next_msg_s["journeyStep"]

                            async def _journey_stream_gen():
                                yield _sse({"done": True, "conversationId": conversation_id_s, "mode": "journey", "journeyStep": next_step_val})

                            return StreamingResponse(_journey_stream_gen(), media_type="text/event-stream")

    if eff_agent_id_stream:
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


@router.post("/plan-execute")
async def plan_execute_via_task_stream(req: Request) -> dict[str, Any]:
    """
    Start plan execution via the task-stream system.

    Note: Plan execution is also triggered automatically when sending "approve"
    via /message or /message/background. This endpoint exists as a fallback
    or for explicit task stream control.

    This method:
    - Survives page refreshes (durable to Redis/Postgres)
    - Provides real-time streaming updates via SSE (no polling needed)
    - Allows resume after reconnection

    Returns:
        streamId: The task stream ID to subscribe to for real-time updates
        planId: The plan being executed
        conversationId: The conversation ID
        status: "running" if the stream was started/resumed

    Frontend should subscribe to: /api/v1/task-stream/events/{streamId}
    """
    body = await req.json()

    # Plan access check
    bg_conv_id = str(body.get("conversationId") or "").strip()
    bg_agent_id = str(body.get("agentId") or "").strip()
    if bg_conv_id and not bg_agent_id:
        bg_conv = await get_conversation(bg_conv_id)
        if bg_conv:
            bg_agent_id = str(bg_conv.get("agentId") or "").strip()
    if bg_agent_id:
        await _enforce_agent_access(req, bg_agent_id)

    return await agent_router.start_plan_via_task_stream(body)


AGENT_INITIAL_MESSAGES: dict[str, dict[str, Any]] = {
    "business_problem_identifier": {
        "content": "What outcome are you looking to achieve?",
        "options": journey_service.get_outcome_options(),
        "kind": "final",
        "allowCustomAnswer": False,
        "journeyStep": journey_service.JOURNEY_STEP_OUTCOME,
    },
}


@router.post("/conversations")
async def create_conversation(req: Request) -> dict[str, Any]:
    body = await req.json()
    agent_id = str(body.get("agentId") or "").strip() or None
    session_id = str(body.get("sessionId") or "").strip() or None
    onboarding_session_id = str(body.get("onboardingSessionId") or "").strip() or session_id
    user_id = str(body.get("userId") or "").strip() or None

    if not agent_id:
        raise HTTPException(status_code=400, detail="agentId is required")

    # ── Plan access check ──
    await _enforce_agent_access(req, agent_id)

    # Keep onboarding and chat tied to one canonical session actor key.
    conv = await create_new_conversation(agent_id, session_id=onboarding_session_id, user_id=user_id)
    conversation_id = conv["id"]

    initial = AGENT_INITIAL_MESSAGES.get(agent_id)
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


