from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Literal

from app.phase2.agent.orchestrator import RunOpts, run_agent_turn_stream
from app.phase2.stores import (
    append_assistant_placeholder,
    append_message,
    get_or_create_conversation,
    get_skill_calls_by_message_id,
    get_stage_outputs,
    save_stage_outputs,
    update_message_content,
)
from app.phase2.router import _resolve_agent_and_skill
from app.services import unified_chat_service


ChatIntent = Literal["standard", "agentic"]


def detect_intent(message: str, agent_id: str | None) -> ChatIntent:
    _ = message  # Reserved for future intent heuristics.
    if (agent_id or "").strip():
        return "agentic"
    return "standard"


def _actor_from_payload(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip() or None
    user_id = str(payload.get("userId") or payload.get("user_id") or "").strip() or None
    return session_id, user_id


async def run_message(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")

    requested_agent_id = str(payload.get("agentId") or "").strip() or None
    intent = detect_intent(message, requested_agent_id)
    session_id, user_id = _actor_from_payload(payload)

    if intent == "standard":
        out = await unified_chat_service.run_standard_chat(
            message=message,
            persona=str(payload.get("persona") or "default"),
            context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
            conversation_history=payload.get("conversationHistory") if isinstance(payload.get("conversationHistory"), list) else None,
            conversation_id=str(payload.get("conversationId") or "").strip() or None,
            session_id=session_id,
            user_id=user_id,
        )
        return {
            "mode": "standard",
            "intent": intent,
            "conversationId": out["conversationId"],
            "message": out["message"],
            "usage": out.get("usage"),
            "stageOutputs": {},
            "outputFile": None,
            "agentId": None,
        }

    resolved = await _resolve_agent_and_skill(payload)
    conv = await get_or_create_conversation(
        str(payload.get("conversationId") or "").strip() or None,
        resolved["agentId"],
        session_id=session_id,
        user_id=user_id,
    )
    await append_message(conv["id"], "user", message)
    assistant_message_id = await append_assistant_placeholder(conv["id"])
    merged_stage_outputs = await get_stage_outputs(conv["id"])

    token_parts: list[str] = []

    async def _on_stage(_stage: str, _label: str, _idx: int) -> None:
        return None

    async def _on_token(token: str) -> None:
        token_parts.append(token)

    result = await run_agent_turn_stream(
        message,
        conv.get("messages") or [],
        resolved["skillId"],
        on_stage=_on_stage,
        on_token=_on_token,
        on_progress=None,
        opts=RunOpts(
            allowed_skill_ids=resolved.get("allowedSkillIds") or None,
            contexts=resolved.get("contexts") or {},
            conversation_id=conv["id"],
            message_id=assistant_message_id,
        ),
    )

    text = "".join(token_parts).strip() or (result.text or "").strip()
    if result.status == "error" and not text:
        text = "I could not run the automation for this request. Please try again."

    skills_count = len(await get_skill_calls_by_message_id(assistant_message_id))
    await update_message_content(conv["id"], assistant_message_id, text, None, skills_count)
    await save_stage_outputs(conv["id"], merged_stage_outputs, None)

    return {
        "mode": "agentic",
        "intent": intent,
        "conversationId": conv["id"],
        "messageId": assistant_message_id,
        "message": text,
        "runId": result.run_id,
        "model": result.model,
        "durationMs": result.duration_ms,
        "stageOutputs": merged_stage_outputs,
        "outputFile": None,
        "agentId": resolved["agentId"],
    }


async def run_stream(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")

    requested_agent_id = str(payload.get("agentId") or "").strip() or None
    intent = detect_intent(message, requested_agent_id)
    session_id, user_id = _actor_from_payload(payload)

    if intent == "standard":
        out = await unified_chat_service.run_standard_chat(
            message=message,
            persona=str(payload.get("persona") or "default"),
            context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
            conversation_history=payload.get("conversationHistory") if isinstance(payload.get("conversationHistory"), list) else None,
            conversation_id=str(payload.get("conversationId") or "").strip() or None,
            session_id=session_id,
            user_id=user_id,
        )
        yield {"token": out["message"]}
        yield {
            "done": True,
            "mode": "standard",
            "intent": intent,
            "conversationId": out["conversationId"],
            "usage": out.get("usage"),
            "stageOutputs": {},
            "outputFile": None,
            "agentId": None,
        }
        return

    resolved = await _resolve_agent_and_skill(payload)
    conv = await get_or_create_conversation(
        str(payload.get("conversationId") or "").strip() or None,
        resolved["agentId"],
        session_id=session_id,
        user_id=user_id,
    )
    await append_message(conv["id"], "user", message)
    assistant_message_id = await append_assistant_placeholder(conv["id"])
    merged_stage_outputs = await get_stage_outputs(conv["id"])

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    done = asyncio.Event()
    tokens_emitted = 0

    async def _on_stage(stage: str, label: str, idx: int) -> None:
        await queue.put(
            {
                "stage": stage,
                "label": label,
                "stageIndex": idx,
                "agentId": resolved["agentId"],
            }
        )

    async def _on_token(token: str) -> None:
        nonlocal tokens_emitted
        tokens_emitted += len(token)
        await queue.put({"token": token})

    async def _worker() -> None:
        try:
            await queue.put({"stage": "thinking", "label": "Thinking", "stageIndex": 0, "agentId": resolved["agentId"]})
            result = await run_agent_turn_stream(
                message,
                conv.get("messages") or [],
                resolved["skillId"],
                on_stage=_on_stage,
                on_token=_on_token,
                on_progress=lambda e: queue.put_nowait({"progress": e}),
                opts=RunOpts(
                    allowed_skill_ids=resolved.get("allowedSkillIds") or None,
                    contexts=resolved.get("contexts") or {},
                    conversation_id=conv["id"],
                    message_id=assistant_message_id,
                ),
            )

            text = result.text or ""
            if result.status == "error" and not text:
                text = "I could not run the automation for this request. Please try again."
            if text and tokens_emitted == 0:
                await queue.put({"token": text})

            skills_count = len(await get_skill_calls_by_message_id(assistant_message_id))
            await update_message_content(conv["id"], assistant_message_id, text, None, skills_count)
            await save_stage_outputs(conv["id"], merged_stage_outputs, None)

            await queue.put(
                {
                    "done": True,
                    "mode": "agentic",
                    "intent": intent,
                    "conversationId": conv["id"],
                    "messageId": assistant_message_id,
                    "runId": result.run_id,
                    "model": result.model,
                    "durationMs": result.duration_ms,
                    "stageOutputs": merged_stage_outputs,
                    "outputFile": None,
                    "agentId": resolved["agentId"],
                }
            )
        except Exception as exc:  # pragma: no cover
            await queue.put({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
        finally:
            done.set()

    asyncio.create_task(_worker())

    while not done.is_set() or not queue.empty():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15)
            yield event
        except asyncio.TimeoutError:
            yield {"ping": True}

