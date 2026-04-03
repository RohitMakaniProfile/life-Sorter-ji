"""
OpenRouter LLM call wrapper.

Eliminates boilerplate when calling openrouter_service — no need to
repeat model/temperature/max_tokens or build the messages list every time.

Usage (blocking — just text):
    from app.wrapper.openrouter import OpenRouter

    llm = OpenRouter(temperature=0.5, max_tokens=5000)
    text = await llm.complete(system="You are...", user="Context here")

Usage (blocking — text + usage for logging):
    result = await llm.complete_full(system="...", user="...")
    text  = result["message"]
    usage = result["usage"]   # prompt_tokens, completion_tokens, total_tokens

Usage (streaming):
    async def on_token(token: str) -> None:
        await queue.put(token)

    text = await llm.stream(system="...", user="...", on_token=on_token)

Default model is OPENROUTER_MODEL (GLM — the main model used across the app).
For playbook / Claude calls, pass model=get_settings().OPENROUTER_CLAUDE_MODEL explicitly.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.config import get_settings
from app.services.ai_helper import AIHelper

TokenCb = Callable[[str], Awaitable[None] | None]
_ai = AIHelper()


class OpenRouter:
    """
    Thin wrapper around openrouter_service for single system+user calls.

    Args:
        model:       OpenRouter model ID. Defaults to OPENROUTER_MODEL (GLM) from config.
        temperature: Sampling temperature. Default 0.7.
        max_tokens:  Max tokens to generate. Default 4096.
    """

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self._model = model  # resolved lazily so settings are read at call time
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def model(self) -> str:
        # Default = OPENROUTER_MODEL (z-ai/glm-5) — same as 90% of codebase
        return self._model or get_settings().OPENROUTER_MODEL

    # ── Blocking — returns just the text string ────────────────

    async def complete(self, system: str, user: str) -> str:
        """
        Single LLM call. Returns the generated text only.

        Use complete_full() if you also need usage stats for logging.
        """
        result = await _ai.complete(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return result["message"]

    # ── Blocking — returns full dict (text + usage) ────────────

    async def complete_full(self, system: str, user: str) -> dict[str, Any]:
        """
        Single LLM call. Returns {"message": str, "usage": {...}}.

        Use this when you need usage stats (e.g. logging LLM calls elsewhere).

        Example:
            result = await llm.complete_full(system=PROMPT, user=ctx)
            text  = result["message"]
            usage = result["usage"]   # prompt_tokens, completion_tokens, total_tokens
        """
        return await _ai.complete(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    # ── Streaming — returns full text when done ────────────────

    async def stream(
        self,
        system: str,
        user: str,
        on_token: TokenCb | None = None,
    ) -> str:
        """
        Streaming LLM call. Calls on_token(token) for each chunk.
        Returns the full accumulated text when done.

        Example:
            async def on_token(token: str) -> None:
                await queue.put(token)

            text = await llm.stream(system=PROMPT, user=ctx, on_token=on_token)
        """
        result = await _ai.complete_stream(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            on_token=on_token,
        )
        return result["message"]

    # ── Multi-turn / custom messages list ─────────────────────

    async def complete_messages(self, messages: list[dict]) -> str:
        """
        For multi-turn or non-standard message shapes. Returns text only.

        Example:
            text = await llm.complete_messages([
                {"role": "system",    "content": "..."},
                {"role": "user",      "content": "first turn"},
                {"role": "assistant", "content": "..."},
                {"role": "user",      "content": "follow-up"},
            ])
        """
        result = await _ai.complete(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return result["message"]

    async def complete_messages_full(self, messages: list[dict]) -> dict[str, Any]:
        """Multi-turn variant that returns {"message": str, "usage": {...}}."""
        return await _ai.complete(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    async def stream_messages(
        self,
        messages: list[dict],
        on_token: TokenCb | None = None,
    ) -> str:
        """Streaming version of complete_messages. Returns full text when done."""
        result = await _ai.complete_stream(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            on_token=on_token,
        )
        return result["message"]
