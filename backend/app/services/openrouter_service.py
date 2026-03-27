from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

import httpx

from app.config import get_settings

TokenCb = Callable[[str], Awaitable[None] | None]
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict):
                txt = part.get("text")
                if isinstance(txt, str):
                    chunks.append(txt)
        return "".join(chunks)
    return str(content or "")


def _headers() -> dict[str, str]:
    settings = get_settings()
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        raise ValueError("OPENROUTER_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ikshan.ai",
        "X-Title": "Ikshan Unified LLM",
    }


async def chat_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(OPENROUTER_CHAT_URL, json=payload, headers=_headers())
        resp.raise_for_status()
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    message = _extract_text((choice.get("message") or {}).get("content"))
    usage = data.get("usage") or {}
    return {
        "message": message.strip(),
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


async def chat_completion_stream(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
    on_token: TokenCb | None = None,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    full_text = ""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", OPENROUTER_CHAT_URL, json=payload, headers=_headers()) as resp:
            resp.raise_for_status()
            async for raw in resp.aiter_lines():
                line = (raw or "").strip()
                if not line.startswith("data: "):
                    continue
                data_line = line[6:].strip()
                if data_line == "[DONE]":
                    continue
                try:
                    evt = json.loads(data_line)
                except Exception:
                    continue
                choice = (evt.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                token = _extract_text(delta.get("content"))
                if token:
                    full_text += token
                    if on_token:
                        result = on_token(token)
                        if asyncio.iscoroutine(result):
                            await result
    # OpenRouter does not always emit final usage in streamed lines reliably.
    return {
        "message": full_text.strip(),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
