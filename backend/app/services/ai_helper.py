from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from app.config import OPENAI_MODEL, get_settings
from app.services import openrouter_service

TokenCb = Callable[[str], Awaitable[None] | None]


@dataclass
class AiChatResult:
    message: str
    input_tokens: int
    output_tokens: int


def _extract_json_object(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty LLM output; expected JSON")

    try:
        json.loads(raw)
        return raw
    except Exception:
        pass

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    obj = re.search(r"\{[\s\S]*\}", raw)
    if not obj:
        raise ValueError("Could not find a JSON object in LLM output")
    candidate = obj.group(0).strip()
    json.loads(candidate)
    return candidate


def _openrouter_status_code(exc: Exception) -> int | None:
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None) if resp is not None else None
    return code if isinstance(code, int) else None


def openrouter_model_candidates(model_id: str, prefix_env: str = "OPENROUTER_MODEL_PREFIX") -> list[str]:
    raw = (model_id or "").strip()
    if not raw:
        return []
    if "/" in raw:
        return [raw]

    prefix = (os.getenv(prefix_env, "google/") or "").strip().rstrip("/") + "/"
    candidate = f"{prefix}{raw}"
    if candidate == raw:
        return [raw]
    return [candidate, raw]


async def complete(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    return await openrouter_service.chat_completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def complete_stream(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
    on_token: TokenCb | None = None,
) -> dict[str, Any]:
    return await openrouter_service.chat_completion_stream(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        on_token=on_token,
    )


async def complete_json(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    result = await complete(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    parsed = json.loads(_extract_json_object(str(result.get("message") or "")))
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object but got non-object JSON")
    return parsed


async def complete_json_with_candidates(
    *,
    model_candidates: list[str],
    messages: list[dict[str, Any]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for model in model_candidates:
        try:
            return await complete_json(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            last_exc = exc
            status = _openrouter_status_code(exc)
            if status in (404, 429, 503) or (isinstance(exc, httpx.HTTPStatusError) and status in (429, 503)):
                continue
            break

    if last_exc:
        raise last_exc
    raise RuntimeError("No model candidates available")


class AIHelper:
    """
    Central OpenRouter-backed AI helper used across backend.

    Provides:
    - normal completion
    - streaming completion
    - strict JSON completion
    - multi-model candidate fallback
    - model id candidate mapping
    """

    @staticmethod
    def model_candidates(model_id: str, prefix_env: str = "OPENROUTER_MODEL_PREFIX") -> list[str]:
        return openrouter_model_candidates(model_id, prefix_env=prefix_env)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return await complete(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def complete_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        on_token: TokenCb | None = None,
    ) -> dict[str, Any]:
        return await complete_stream(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            on_token=on_token,
        )

    async def complete_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return await complete_json(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def complete_json_with_candidates(
        self,
        *,
        model_candidates: list[str],
        messages: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return await complete_json_with_candidates(
            model_candidates=model_candidates,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat(
        self,
        message: str,
        system_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        provider: str | None = None,
    ) -> AiChatResult:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in (conversation_history or []):
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        settings = get_settings()
        model_id = settings.OPENROUTER_MODEL or OPENAI_MODEL
        if provider in {"anthropic", "claude"}:
            model_id = settings.OPENROUTER_CLAUDE_MODEL or model_id

        response = await self.complete(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,
        )
        usage = response.get("usage") or {}
        return AiChatResult(
            message=str(response.get("message") or "").strip(),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    async def chat_stream(
        self,
        message: str,
        system_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
        on_token: TokenCb | None = None,
        temperature: float = 0.7,
        provider: str | None = None,
    ) -> AiChatResult:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in (conversation_history or []):
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})

        settings = get_settings()
        model_id = settings.OPENROUTER_MODEL or OPENAI_MODEL
        if provider in {"anthropic", "claude"}:
            model_id = settings.OPENROUTER_CLAUDE_MODEL or model_id

        streamed = await self.complete_stream(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,
            on_token=on_token,
        )
        usage = streamed.get("usage") or {}
        return AiChatResult(
            message=str(streamed.get("message") or "").strip(),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


ai_helper = AIHelper()
