"""
═══════════════════════════════════════════════════════════════
OPENAI SERVICE — Async wrapper for LLM chat operations
═══════════════════════════════════════════════════════════════
Provides:
  • chat_completion() — multi-persona chat with history
"""

from __future__ import annotations

from typing import Optional

import structlog

from app.config import get_settings
from app.data.personas import build_system_prompt
from app.services import openrouter_service

logger = structlog.get_logger()


# ── Chat Completion ────────────────────────────────────────────


async def chat_completion(
    message: str,
    persona: str = "default",
    context: Optional[dict] = None,
    conversation_history: Optional[list[dict]] = None,
) -> dict:
    """
    Generate a chat completion using OpenAI.

    Args:
        message: The user's message text.
        persona: One of 'product', 'contributor', 'assistant', 'default'.
        context: Optional context dict (generateBrief, domain, subDomain, etc.).
        conversation_history: List of prior {role, content} messages.

    Returns:
        dict with 'message' (str) and 'usage' (dict) keys.
    """
    settings = get_settings()

    # Build system prompt from persona
    system_prompt = build_system_prompt(persona, context)

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    if conversation_history:
        messages.extend(conversation_history)

    # Add current user message
    messages.append({"role": "user", "content": message})

    # Tune parameters based on context
    is_generating_brief = context and context.get("generateBrief", False)
    is_redirecting = context and context.get("isRedirecting", False)

    temperature = 0.5 if is_generating_brief else 0.7
    max_tokens = 1500 if is_generating_brief else (150 if is_redirecting else 600)

    logger.info(
        "OpenAI chat request",
        persona=persona,
        messages_count=len(messages),
        is_brief=is_generating_brief,
        model=settings.OPENAI_MODEL_NAME,
    )

    response = await openrouter_service.chat_completion(
        model=settings.OPENROUTER_MODEL or settings.OPENAI_MODEL_NAME,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    ai_message = response.get("message") or "Sorry, I could not generate a response."
    usage = response.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    logger.info("OpenAI chat response received", usage=usage)

    return {"message": ai_message, "usage": usage}


# ── Company Search GPT ─────────────────────────────────────────


async def company_search_gpt(
    search_prompt: str,
    query: str,
) -> str:
    """
    Use GPT for intelligent company search/scoring.

    Args:
        search_prompt: The full system prompt with company data.
        query: The user's search requirement.

    Returns:
        Raw GPT response string (JSON expected).
    """
    settings = get_settings()
    response = await openrouter_service.chat_completion(
        model=settings.OPENROUTER_MODEL or settings.OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": search_prompt},
            {"role": "user", "content": f'Find the best startups for: "{query}"'},
        ],
        temperature=0.2,
        max_tokens=500,
    )
    return response.get("message") or ""


async def company_explanation_gpt(
    explanation_prompt: str,
    query: str,
) -> str:
    """
    Generate a helpful explanation of matched companies.

    Args:
        explanation_prompt: System prompt with matched company details.
        query: The user's requirement text.

    Returns:
        Human-friendly explanation string.
    """
    settings = get_settings()
    response = await openrouter_service.chat_completion(
        model=settings.OPENROUTER_MODEL or settings.OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": explanation_prompt},
            {"role": "user", "content": f'Explain these tools for: "{query}"'},
        ],
        temperature=0.7,
        max_tokens=600,
    )
    return response.get("message") or ""


