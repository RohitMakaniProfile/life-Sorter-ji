from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from ..ai import AiHelper
from ..config import CLAUDE_API_KEY, CLAUDE_MODEL

TokenCb = Callable[[str], Awaitable[None] | None]


@dataclass
class FormatterResult:
    run_id: str
    status: str
    text: str
    error: str | None
    stage_outputs: dict[str, Any]
    duration_ms: int


async def format_final_answer(
    *,
    message: str,
    start_ms: float,
    skill_calls: list[dict[str, Any]],
    last_skill_result: dict[str, Any] | None,
    contexts: dict[str, str],
    on_token: TokenCb | None = None,
) -> FormatterResult:
    """
    Produce the final user-facing answer by summarizing all skill calls.
    Uses streaming LLM (Claude if available, else OpenAI).
    """
    skills_markdown = "\n".join(
        f"### {c.get('skillId', '?')}\n\n{(c.get('rawText') or '').strip() or '(no summary available)'}\n"
        for c in skill_calls
    )

    formatter_ai = (
        AiHelper(temperature=0.3, provider="anthropic")
        if CLAUDE_API_KEY
        else AiHelper(temperature=0.3)
    )

    final_output_context = (contexts.get("finalOutputFormattingContext") or "").strip()

    if final_output_context:
        prompt = "\n".join([
            final_output_context,
            "",
            f"User message:\n{message}",
            "",
            "Skill summaries (markdown):",
            skills_markdown,
        ])
        system = "You produce the final user-facing output using all provided context."
    else:
        prompt = "\n".join([
            "You are the final formatter for a multi-skill business intelligence agent.",
            "Summarize ALL of the following skill calls into one coherent answer for the user.",
            "General rules:",
            "- Preserve as much detail as possible; do not aggressively shorten.",
            "- Include insights from EVERY successful skill output that is relevant to the user message.",
            "- Clearly label which platform/source each insight comes from (website, Google Business, Quora, Instagram, Play Store, YouTube, etc.).",
            "- Do NOT invent facts not supported by the data.",
            "",
            f"User message:\n{message}",
            "",
            "Skill summaries (markdown):",
            skills_markdown,
        ])
        system = "You generate a detailed, faithful summary of all provided tool outputs for the user."

    full_text = ""
    stream_result = await formatter_ai.chat_stream(
        message=prompt,
        system_prompt=system,
        on_token=on_token,
    )
    full_text = (stream_result.message or full_text).strip()

    run_id = (last_skill_result or {}).get("runId") or f"orchestrator-{int(time.time() * 1000)}"
    status = (last_skill_result or {}).get("status") or "ok"
    error = (last_skill_result or {}).get("error")
    stage_outputs = (last_skill_result or {}).get("stageOutputs") or {}
    duration_ms = int((time.time() - start_ms / 1000) * 1000) if start_ms > 1e9 else int(time.time() * 1000 - start_ms)

    return FormatterResult(
        run_id=run_id,
        status=status,
        text=full_text,
        error=error,
        stage_outputs=stage_outputs,
        duration_ms=duration_ms,
    )
