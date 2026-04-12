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
    stop_reason: str = ""


def _extract_json_value(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty LLM output; expected JSON")

    # 0. Strip <thinking>...</thinking> blocks (Claude extended thinking mode)
    # First pass: strip any properly closed <thinking>...</thinking> blocks (non-greedy, handles multiple blocks)
    raw = re.sub(r"<thinking>[\s\S]*?</thinking>", "", raw, flags=re.IGNORECASE).strip()
    # Second pass: handle unclosed <thinking> block (output truncated before </thinking> tag)
    # If any <thinking> tag remains without a matching </thinking>, strip from that point to end-of-string
    if re.search(r"<thinking>", raw, re.IGNORECASE):
        raw = re.sub(r"<thinking>[\s\S]*$", "", raw, flags=re.IGNORECASE).strip()
    if not raw:
        raise ValueError("LLM output only contained a <thinking> block with no JSON")

    # 1. Try to parse the whole string as JSON
    try:
        json.loads(raw)
        return raw
    except Exception:
        pass

    # 2. Try to extract from markdown code fences (```json ... ``` or ``` ... ```)
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    # 3. Find balanced JSON using bracket matching
    def find_balanced_json(text: str, start: int) -> str | None:
        """Find a balanced JSON object/array starting at position `start`."""
        if start >= len(text):
            return None
        open_ch = text[start]
        if open_ch not in "{[":
            return None
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    # Try all JSON-like starting positions, preferring objects over arrays
    obj_starts = [i for i, ch in enumerate(raw) if ch == "{"]
    arr_starts = [i for i, ch in enumerate(raw) if ch == "["]

    # First try object starts (more common for structured responses)
    for start in obj_starts:
        candidate = find_balanced_json(raw, start)
        if candidate:
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                continue

    # Then try array starts
    for start in arr_starts:
        candidate = find_balanced_json(raw, start)
        if candidate:
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                continue

    # 4. As a last resort, try simple end-position matching (original fallback)
    starts = [i for i, ch in enumerate(raw) if ch in "[{"]
    if not starts:
        raise ValueError("Could not find JSON-looking content in LLM output")

    for start in starts:
        open_ch = raw[start]
        close_ch = "}" if open_ch == "{" else "]"
        end_positions = [i for i in range(len(raw) - 1, start, -1) if raw[i] == close_ch]
        for end in end_positions:
            candidate = raw[start : end + 1].strip()
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                continue

    raise ValueError("Could not extract valid JSON from LLM output")


def _extract_json_object(text: str) -> str:
    candidate = _extract_json_value(text)
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object but got non-object JSON")
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
            stop_reason=str(response.get("finish_reason") or ""),
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
            stop_reason=str(streamed.get("finish_reason") or ""),
        )


ai_helper = AIHelper()
