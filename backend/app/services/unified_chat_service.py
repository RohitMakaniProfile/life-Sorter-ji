from __future__ import annotations

from typing import Any

from app.doable_claw_agent.stores import append_message, get_or_create_conversation
from app.services import openai_service


def _normalize_history(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items or []:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role in {"user", "assistant", "system"} and content:
            out.append({"role": role, "content": content})
    return out


async def run_standard_chat(
    *,
    message: str,
    persona: str = "default",
    context: dict[str, Any] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    conversation_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    conv = await get_or_create_conversation(
        conversation_id,
        agent_id="assistant",
        session_id=session_id,
        user_id=user_id,
    )

    existing = _normalize_history(conv.get("messages"))
    inbound = _normalize_history(conversation_history)
    history = existing if existing else inbound

    await append_message(conv["id"], "user", message)
    result = await openai_service.chat_completion(
        message=message,
        persona=persona,
        context=context,
        conversation_history=history,
    )
    text = str(result.get("message") or "").strip()
    await append_message(conv["id"], "assistant", text)
    return {
        "message": text,
        "usage": result.get("usage"),
        "conversationId": conv["id"],
    }
