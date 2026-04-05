"""
Plan Approval Execution Task Stream

Runs the plan execution in a background task with durable streaming updates.
This replaces the polling-based plan-status endpoint.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.db import get_pool
from app.services.agent_checklist_service import (
    prepare_plan_approval,
    execute_plan_approval_work,
)
from app.doable_claw_agent.stores import (
    append_assistant_placeholder,
    get_plan_run,
)
from app.task_stream.registry import register_task_stream

logger = structlog.get_logger()


@register_task_stream("plan/execute")
async def plan_execute_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Execute an approved plan as a background task stream.

    This task is triggered automatically when user sends "approve" via /message
    or /message/background. The response includes taskStream metadata with the
    streamId for the frontend to subscribe to real-time updates.

    Input payload:
      - plan_id: str (required)
      - conversation_id: str (required)
      - agent_id: str (required)
      - message: str (optional, for context)
      - session_id: str (optional)
      - user_id: str (optional)

    Emits:
      - stage events (thinking, executing, etc.)
      - progress events (skill calls, checklist updates)
      - token events (for final answer streaming)
      - done with { final_answer, conversation_id, plan_id }
    """
    plan_id = str(payload.get("plan_id") or "").strip()
    conversation_id = str(payload.get("conversation_id") or "").strip()
    agent_id = str(payload.get("agent_id") or "").strip()

    if not plan_id:
        raise ValueError("plan_id is required for plan/execute")
    if not agent_id:
        raise ValueError("agent_id is required for plan/execute")

    # Build the body format expected by prepare_plan_approval
    body = {
        "planId": plan_id,
        "conversationId": conversation_id,
        "agentId": agent_id,
        "message": payload.get("message", ""),
        "sessionId": payload.get("session_id"),
        "userId": payload.get("user_id"),
    }

    await send("stage", stage="preparing", label="Preparing plan execution...")

    try:
        conv, plan, resolved, plan_id, session_id = await prepare_plan_approval(body)
    except Exception as exc:
        logger.error("plan/execute prepare failed", plan_id=plan_id, error=str(exc))
        raise ValueError(f"Failed to prepare plan: {exc}")

    assistant_message_id = await append_assistant_placeholder(conv["id"])

    # Wrap emit functions for task stream
    async def emit(event: dict[str, Any]) -> None:
        event_type = event.get("stage") or event.get("type") or "update"
        if event.get("done"):
            # Don't send done here - we handle it at the end
            return
        if "token" in event:
            await send("token", token=event["token"])
        elif "progress" in event:
            await send("progress", **event["progress"])
        else:
            # Send stage/status updates
            await send(event_type, **{k: v for k, v in event.items() if k != "type"})

    async def emit_progress(event: dict[str, Any]) -> None:
        await send("progress", **event)

    await send("stage", stage="executing", label="Executing plan...")

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
    except Exception as exc:
        logger.error("plan/execute work failed", plan_id=plan_id, error=str(exc))
        # Update plan status to error
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE plan_runs
                SET status = 'error', error_message = $1, updated_at = NOW()
                WHERE id = $2
                """,
                str(exc),
                plan_id,
            )
        raise

    # Get final plan state
    final_plan = await get_plan_run(plan_id)

    logger.info("plan/execute done", plan_id=plan_id, conversation_id=conv["id"])

    return {
        "plan_id": plan_id,
        "conversation_id": conv["id"],
        "status": final_plan.get("status") if final_plan else "complete",
        "assistant_message_id": assistant_message_id,
    }

