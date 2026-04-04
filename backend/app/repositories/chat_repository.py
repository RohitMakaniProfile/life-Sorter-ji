from __future__ import annotations

from typing import Any

from app.db import get_pool
from app.doable_claw_agent.stores import (
    delete_conversation,
    get_or_create_conversation,
    get_skill_calls_by_message_id_full,
    get_token_usage,
    list_conversations,
    now_iso,
)
from app.skills.service import list_skills


async def _attach_playbook_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Post-processor: if the last assistant message is the playbook placeholder
    (journeyStep == "playbook"), look up the completed playbook from
    playbook_runs and inject it as an additional assistant message.
    """
    if not messages:
        return messages

    # Find the playbook placeholder message (scan from end)
    playbook_msg_idx: int | None = None
    session_id: str = ""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if (
            msg.get("role") == "assistant"
            and msg.get("journeyStep") == "playbook"
        ):
            selections = msg.get("journeySelections") or {}
            sid = str(selections.get("onboardingSessionId") or "").strip()
            if sid:
                playbook_msg_idx = i
                session_id = sid
            break

    if playbook_msg_idx is None or not session_id:
        return messages

    # Check if playbook content already exists as a subsequent message
    for j in range(playbook_msg_idx + 1, len(messages)):
        subsequent = messages[j]
        if (
            subsequent.get("role") == "assistant"
            and subsequent.get("journeyStep") == "playbook_content"
        ):
            # Already attached in a prior call or stored — nothing to do
            return messages

    # Look up completed playbook from playbook_runs
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT playbook, website_audit, context_brief, icp_card, status
            FROM playbook_runs
            WHERE session_id = $1
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            session_id,
        )

    if not row or row["status"] != "complete":
        return messages

    playbook_text = str(row["playbook"] or "").strip()
    if not playbook_text:
        return messages

    # Build the playbookData object matching the frontend PlaybookData interface
    playbook_data: dict[str, str] = {
        "playbook": playbook_text,
        "websiteAudit": str(row["website_audit"] or "").strip(),
        "contextBrief": str(row["context_brief"] or "").strip(),
        "icpCard": str(row["icp_card"] or "").strip(),
    }

    # Extract websiteUrl from the placeholder message's journeySelections
    placeholder_selections = messages[playbook_msg_idx].get("journeySelections") or {}
    website_url = str(placeholder_selections.get("websiteUrl") or "").strip()

    # Build cross-agent actions (e.g. "Do Deep Analysis" → research-orchestrator)
    cross_agent_actions: list[dict[str, str]] = []
    if website_url:
        cross_agent_actions.append({
            "label": "Do Deep Analysis",
            "icon": "🔬",
            "agentId": "research-orchestrator",
            "initialMessage": f"Do deep analysis of {website_url}",
        })

    # Inject the playbook as an additional assistant message right after the placeholder
    playbook_content_msg: dict[str, Any] = {
        "role": "assistant",
        "content": playbook_text,
        "createdAt": now_iso(),
        "journeyStep": "playbook_content",
        "playbookData": playbook_data,
    }
    if cross_agent_actions:
        playbook_content_msg["crossAgentActions"] = cross_agent_actions

    result = list(messages)
    result.insert(playbook_msg_idx + 1, playbook_content_msg)
    return result


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
    messages = conv.get("messages") or []
    messages = await _attach_playbook_content(messages)
    return {
        "messages": messages,
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

