from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from app.config import OPENAI_MODEL, get_settings
from app.services import openrouter_service

TokenCb = Callable[[str], Awaitable[None] | None]


@dataclass
class AiChatResult:
    message: str
    input_tokens: int
    output_tokens: int


class AiHelper:
    """
    Thin LLM wrapper using a single OpenRouter backend.
    """

    def __init__(self, temperature: float = 0.7, provider: str | None = None) -> None:
        self._temperature = temperature
        self._provider = provider or "openrouter"

    async def chat(
        self,
        message: str,
        system_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AiChatResult:
        history = conversation_history or []
        return await self._chat_openai(message, system_prompt, history)

    async def _chat_openai(
        self,
        message: str,
        system_prompt: str,
        history: list[dict[str, Any]],
    ) -> AiChatResult:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        settings = get_settings()
        response = await openrouter_service.chat_completion(
            model=settings.OPENROUTER_MODEL or OPENAI_MODEL,
            messages=messages,
            temperature=self._temperature,
            max_tokens=8192,
        )
        usage = response.get("usage") or {}
        content = str(response.get("message") or "").strip()
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return AiChatResult(message=content, input_tokens=input_tokens, output_tokens=output_tokens)

    async def chat_stream(
        self,
        message: str,
        system_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
        on_token: TokenCb | None = None,
    ) -> AiChatResult:
        history = conversation_history or []
        return await self._chat_stream_openai(message, system_prompt, history, on_token)

    async def _chat_stream_openai(
        self,
        message: str,
        system_prompt: str,
        history: list[dict[str, Any]],
        on_token: TokenCb | None,
    ) -> AiChatResult:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        settings = get_settings()
        streamed = await openrouter_service.chat_completion_stream(
            model=settings.OPENROUTER_MODEL or OPENAI_MODEL,
            messages=messages,
            temperature=self._temperature,
            max_tokens=8192,
            on_token=on_token,
        )
        usage = streamed.get("usage") or {}
        full_text = str(streamed.get("message") or "")
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return AiChatResult(message=full_text.strip(), input_tokens=input_tokens, output_tokens=output_tokens)
