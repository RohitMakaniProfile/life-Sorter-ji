from __future__ import annotations

"""
Backward-compatible shim around `AIHelper`.

New code should import and use `AIHelper` from `app.services.ai_helper` directly.
"""

from typing import Any, Awaitable, Callable

from app.services.ai_helper import (
    AIHelper,
)


TokenCb = Callable[[str], Awaitable[None] | None]
_ai = AIHelper()


async def chat_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    return await _ai.complete(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)


async def chat_completion_stream(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
    on_token: TokenCb | None = None,
) -> dict[str, Any]:
    return await _ai.complete_stream(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        on_token=on_token,
    )


async def chat_completion_json(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    return await _ai.complete_json(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def try_chat_completion_json_across_candidates(
    *,
    model_candidates: list[str],
    messages: list[dict[str, Any]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    return await _ai.complete_json_with_candidates(
        model_candidates=model_candidates,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def gemini_model_to_openrouter_json(
    *,
    gemini_model_id: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    candidates = AIHelper.model_candidates(gemini_model_id, prefix_env="OPENROUTER_MODEL_PREFIX")
    return await try_chat_completion_json_across_candidates(
        model_candidates=candidates,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

