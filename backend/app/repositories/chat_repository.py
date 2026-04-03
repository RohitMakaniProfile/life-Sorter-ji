from __future__ import annotations

from typing import Any

from app.doable_claw_agent.stores import (
    delete_conversation,
    get_or_create_conversation,
    get_skill_calls_by_message_id_full,
    get_token_usage,
    list_conversations,
)
from app.skills.service import list_skills


async def get_messages(
    conversation_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    conv = await get_or_create_conversation(
        conversation_id,
        session_id=session_id,
        user_id=user_id,
    )
    return {
        "messages": conv.get("messages") or [],
        "conversationId": conv["id"],
        "agentId": conv.get("agentId"),
        "lastStageOutputs": conv.get("lastStageOutputs") or {},
        "lastOutputFile": conv.get("lastOutputFile"),
    }


async def get_conversations(
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    return {
        "conversations": await list_conversations(
            session_id=session_id,
            user_id=user_id,
        )
    }


async def get_skills() -> list[dict[str, Any]]:
    return list_skills()


async def get_skill_calls(message_id: str | None) -> dict[str, Any]:
    if not message_id or not message_id.strip():
        raise ValueError("messageId is required")
    return {"skillCalls": await get_skill_calls_by_message_id_full(message_id.strip())}


async def get_token_usage_by_message(message_id: str | None) -> dict[str, Any]:
    if not message_id or not message_id.strip():
        raise ValueError("messageId is required")
    return await get_token_usage(message_id.strip())


async def delete_conversation_by_id(conversation_id: str) -> dict[str, bool]:
    return {"ok": await delete_conversation(conversation_id)}

