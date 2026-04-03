from __future__ import annotations

from typing import Any

from app.phase2.stores import (
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)

AGENT_MUTABLE_FIELDS = [
    "name",
    "emoji",
    "description",
    "allowedSkillIds",
    "skillSelectorContext",
    "finalOutputFormattingContext",
]


async def get_agents_list() -> list[dict[str, Any]]:
    return await list_agents()


async def get_agent_by_id(agent_id: str) -> dict[str, Any] | None:
    return await get_agent(agent_id)


async def create_new_agent(body: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    if not agent_id:
        raise ValueError("id is required")
    if not name:
        raise ValueError("name is required")
    return await create_agent(
        {
            "id": agent_id,
            "name": name,
            "emoji": body.get("emoji") or "🤖",
            "description": body.get("description") or "",
            "allowedSkillIds": body.get("allowedSkillIds") if isinstance(body.get("allowedSkillIds"), list) else [],
            "skillSelectorContext": body.get("skillSelectorContext") or "",
            "finalOutputFormattingContext": body.get("finalOutputFormattingContext") or "",
        }
    )


async def patch_agent(agent_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    patch: dict[str, Any] = {key: body[key] for key in AGENT_MUTABLE_FIELDS if key in body}
    return await update_agent(agent_id, patch)


async def remove_agent(agent_id: str) -> bool:
    return await delete_agent(agent_id)