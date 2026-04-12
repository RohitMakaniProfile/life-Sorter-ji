from __future__ import annotations

from typing import Any

from app.doable_claw_agent import router as agent_router
from app.doable_claw_agent.stores import append_message, get_conversation, update_plan_run
from app.services import journey_service


async def get_initial_message(agent_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    """
    Returns the initial assistant message for a given agent, or None if the agent
    has no predefined opening message.

    Receives user_id for future user-specific customisation (e.g. personalised
    greetings, plan-tier-aware options).
    """
    if agent_id == "business_problem_identifier":
        return {
            "role": "assistant",
            "content": "What outcome are you looking to achieve?",
            "options": journey_service.get_outcome_options(),
            "kind": "final",
            "allowCustomAnswer": False,
            "journeyStep": journey_service.JOURNEY_STEP_OUTCOME,
            "journeySelections": {},
        }
    return None


def _normalize_option(value: str) -> str:
    return value.strip().lower()


async def _append_journey_message(conversation_id: str, next_msg: dict[str, Any]) -> None:
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


async def _journey_response(conversation_id: str, next_msg: dict[str, Any]) -> dict[str, Any]:
    conv = await get_conversation(conversation_id) or {}
    return {
        "mode": "journey",
        "conversationId": conversation_id,
        "journeyStep": next_msg["journeyStep"],
        "messages": conv.get("messages") or [],
    }


async def handle_send_message_for_problem_identifier_agent(
    body: dict[str, Any],
    conversation: dict[str, Any],
    last_assistant_message: dict[str, Any] | None,
) -> dict[str, Any] | None:
    conversation_id = conversation["id"]
    user_text = str(body.get("message") or "").strip()
    onboarding_id = str(conversation.get("onboardingId") or "").strip()

    # ── Retry playbook from onboarding session ──
    if onboarding_id and user_text.lower() in ("retry playbook", "retry"):
        prev_selections = {"onboardingSessionId": onboarding_id}
        next_msg = await journey_service.next_step(
            journey_service.JOURNEY_STEP_PLAYBOOK, user_text, prev_selections
        )
        if next_msg is not None:
            await append_message(conversation_id, "user", user_text)
            await _append_journey_message(conversation_id, next_msg)
            return await _journey_response(conversation_id, next_msg)

    if not last_assistant_message:
        return None

    step = str(last_assistant_message.get("journeyStep") or "").strip()
    prev_selections = last_assistant_message.get("journeySelections") or {}

    if not step:
        return None

    # ── Option selection ──
    options = last_assistant_message.get("options") or []
    matched_option = next(
        (o for o in options if _normalize_option(o) == _normalize_option(user_text)), None
    )
    if matched_option:
        next_msg = await journey_service.next_step(step, matched_option, prev_selections)
        if next_msg is not None:
            await append_message(conversation_id, "user", matched_option)
            await _append_journey_message(conversation_id, next_msg)
            return await _journey_response(conversation_id, next_msg)

    # ── Free-text: URL step ──
    if step == journey_service.JOURNEY_STEP_URL and user_text:
        await append_message(conversation_id, "user", user_text)
        next_msg = journey_service.start_scale_questions(url=user_text, acc=prev_selections)
        await _append_journey_message(conversation_id, next_msg)
        return await _journey_response(conversation_id, next_msg)

    # ── Free-text: playbook retry step ──
    if step == journey_service.JOURNEY_STEP_PLAYBOOK and user_text:
        await append_message(conversation_id, "user", user_text)
        next_msg = await journey_service.next_step(step, user_text, prev_selections)
        if next_msg is not None:
            await _append_journey_message(conversation_id, next_msg)
            return await _journey_response(conversation_id, next_msg)

    # ── Free-text: diagnostic / precision / gap steps ──
    _FREE_TEXT_STEPS = {
        journey_service.JOURNEY_STEP_DIAGNOSTIC,
        journey_service.JOURNEY_STEP_PRECISION,
        journey_service.JOURNEY_STEP_GAP,
    }
    if step in _FREE_TEXT_STEPS and user_text and last_assistant_message.get("allowCustomAnswer"):
        await append_message(conversation_id, "user", user_text)
        next_msg = await journey_service.next_step(step, user_text, prev_selections)
        if next_msg is not None:
            await _append_journey_message(conversation_id, next_msg)
            return await _journey_response(conversation_id, next_msg)

    return None


async def handle_send_message_for_research_agent(
    body: dict[str, Any],
    conversation: dict[str, Any],
    last_assistant_message: dict[str, Any] | None,
    matched: tuple[dict[str, Any], str, bool] | None,
) -> dict[str, Any] | None:
    if not matched:
        return None

    conversation_id = conversation["id"]
    agent_id = str(conversation.get("agentId") or "").strip()
    last_assistant, selected, already_logged = matched

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

    if lower == "approve" and agent_id and plan_id:
        approve_body = {
            "planId": plan_id,
            "conversationId": conversation_id,
            "planMarkdown": str(last_assistant.get("content") or ""),
            "agentId": agent_id,
            "sessionId": body.get("sessionId"),
            "userId": body.get("userId"),
        }
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