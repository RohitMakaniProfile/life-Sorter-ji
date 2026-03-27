from __future__ import annotations

from typing import Any
from uuid import uuid4


def generate_form_id() -> str:
    return f"form_{uuid4().hex}"


def should_start_form(
    *,
    conversation_id: str,
    role: str,
    content: str,
    active_form_id: str | None,
) -> bool:
    """
    Hook: decide when a new conversational form starts.
    Replace this logic with LLM-based decisioning when ready.
    """
    _ = (conversation_id, role, content, active_form_id)
    return False


def should_end_form(
    *,
    conversation_id: str,
    role: str,
    content: str,
    active_form_id: str | None,
) -> bool:
    """
    Hook: decide when form collection is complete.
    Replace this logic with LLM-based decisioning when ready.
    """
    _ = (conversation_id, role, content, active_form_id)
    return False


async def process_completed_form(
    *,
    conversation_id: str,
    form_id: str,
    form_messages: list[dict[str, Any]],
) -> None:
    """
    Hook: process a completed form payload.
    Wire your execution starter here.
    """
    _ = (conversation_id, form_id, form_messages)
    return None

