from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from .config import CLAUDE_API_KEY, CLAUDE_MODEL, OPENAI_API_KEY, OPENAI_MODEL

TokenCb = Callable[[str], Awaitable[None] | None]


@dataclass
class AiChatResult:
    message: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None


class AiHelper:
    """
    Thin LLM wrapper. Prefers Anthropic (Claude) when CLAUDE_API_KEY is set, falls back to OpenAI.
    """

    def __init__(self, temperature: float = 0.7, provider: str | None = None) -> None:
        self._temperature = temperature
        if provider is None:
            provider = "anthropic" if CLAUDE_API_KEY else "openai"
        self._provider = provider

    async def chat(
        self,
        message: str,
        system_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AiChatResult:
        history = conversation_history or []
        if self._provider == "anthropic":
            return await self._chat_anthropic(message, system_prompt, history)
        return await self._chat_openai(message, system_prompt, history)

    async def _chat_openai(
        self,
        message: str,
        system_prompt: str,
        history: list[dict[str, Any]],
    ) -> AiChatResult:
        import openai

        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=self._temperature,
            max_tokens=8192,
        )

        content = (response.choices[0].message.content or "").strip()
        stop_reason = None
        try:
            stop_reason = response.choices[0].finish_reason  # type: ignore[attr-defined]
        except Exception:
            stop_reason = None
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        return AiChatResult(message=content, input_tokens=input_tokens, output_tokens=output_tokens, stop_reason=stop_reason)

    async def chat_stream(
        self,
        message: str,
        system_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
        on_token: TokenCb | None = None,
    ) -> AiChatResult:
        history = conversation_history or []
        if self._provider == "anthropic":
            return await self._chat_stream_anthropic(message, system_prompt, history, on_token)
        return await self._chat_stream_openai(message, system_prompt, history, on_token)

    async def _chat_stream_openai(
        self,
        message: str,
        system_prompt: str,
        history: list[dict[str, Any]],
        on_token: TokenCb | None,
    ) -> AiChatResult:
        import asyncio
        import openai

        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        full_text = ""
        input_tokens = 0
        output_tokens = 0

        async with client.chat.completions.stream(
            model=OPENAI_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=self._temperature,
            max_tokens=8192,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    full_text += delta
                    if on_token:
                        result = on_token(delta)
                        if asyncio.iscoroutine(result):
                            await result
            final = await stream.get_final_completion()
            if final.usage:
                input_tokens = final.usage.prompt_tokens
                output_tokens = final.usage.completion_tokens
            stop_reason = None
            try:
                stop_reason = final.choices[0].finish_reason  # type: ignore[attr-defined]
            except Exception:
                stop_reason = None

        return AiChatResult(message=full_text.strip(), input_tokens=input_tokens, output_tokens=output_tokens, stop_reason=stop_reason)

    async def _chat_stream_anthropic(
        self,
        message: str,
        system_prompt: str,
        history: list[dict[str, Any]],
        on_token: TokenCb | None,
    ) -> AiChatResult:
        import asyncio
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
        messages: list[dict[str, Any]] = []
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        full_text = ""
        input_tokens = 0
        output_tokens = 0

        async with client.messages.stream(
            model=CLAUDE_MODEL,
            system=system_prompt or "You are a helpful assistant.",
            messages=messages,  # type: ignore[arg-type]
            max_tokens=8192,
            temperature=self._temperature,
        ) as stream:
            async for text in stream.text_stream:
                full_text += text
                if on_token:
                    result = on_token(text)
                    if asyncio.iscoroutine(result):
                        await result
            final_msg = await stream.get_final_message()
            if final_msg.usage:
                input_tokens = final_msg.usage.input_tokens
                output_tokens = final_msg.usage.output_tokens
            stop_reason = None
            try:
                stop_reason = str(getattr(final_msg, "stop_reason", None) or "") or None
            except Exception:
                stop_reason = None

        return AiChatResult(message=full_text.strip(), input_tokens=input_tokens, output_tokens=output_tokens, stop_reason=stop_reason)

    async def _chat_anthropic(
        self,
        message: str,
        system_prompt: str,
        history: list[dict[str, Any]],
    ) -> AiChatResult:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
        messages: list[dict[str, Any]] = []
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        response = await client.messages.create(
            model=CLAUDE_MODEL,
            system=system_prompt or "You are a helpful assistant.",
            messages=messages,  # type: ignore[arg-type]
            max_tokens=8192,
            temperature=self._temperature,
        )

        content = (response.content[0].text if response.content else "").strip()
        stop_reason = None
        try:
            stop_reason = str(getattr(response, "stop_reason", None) or "") or None
        except Exception:
            stop_reason = None
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0
        return AiChatResult(message=content, input_tokens=input_tokens, output_tokens=output_tokens, stop_reason=stop_reason)
