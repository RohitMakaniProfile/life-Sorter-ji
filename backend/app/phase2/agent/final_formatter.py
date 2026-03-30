from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from ..ai import AiHelper
from app.config import CLAUDE_API_KEY, CLAUDE_MODEL, OPENAI_MODEL

TokenCb = Callable[[str], Awaitable[None] | None]


@dataclass
class FormatterResult:
    run_id: str
    status: str
    text: str
    error: str | None
    stage_outputs: dict[str, Any]
    duration_ms: int
    model: str
    provider: str
    input_tokens: int
    output_tokens: int


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
    total_input_tokens = 0
    total_output_tokens = 0

    # First pass
    stream_result = await formatter_ai.chat_stream(message=prompt, system_prompt=system, on_token=on_token)
    chunk = (stream_result.message or "").strip()
    full_text = chunk
    total_input_tokens += int(stream_result.input_tokens or 0)
    total_output_tokens += int(stream_result.output_tokens or 0)

    # If model hit max tokens, auto-continue a few times.
    # This prevents "random" cut-offs for long reports (Claude/OpenAI max_tokens=8192 in AiHelper).
    for _ in range(3):
        stop = (stream_result.stop_reason or "").lower()
        hit_limit = stop in {"max_tokens", "length"} or int(stream_result.output_tokens or 0) >= 8192
        if not hit_limit:
            break
        tail = full_text[-2000:]
        continue_prompt = "\n".join(
            [
                "Continue the report from EXACTLY where you left off.",
                "Rules:",
                "- Do not repeat any already-written text.",
                "- Keep the same markdown structure and continue incomplete sections.",
                "- Output ONLY the continuation.",
                "",
                "Last output tail (for continuity, do not repeat):",
                tail,
            ]
        )
        stream_result = await formatter_ai.chat_stream(
            message=continue_prompt,
            system_prompt=system,
            conversation_history=[{"role": "assistant", "content": full_text}],
            on_token=on_token,
        )
        next_chunk = (stream_result.message or "").strip()
        if not next_chunk:
            break
        # Ensure we don't accidentally duplicate tail on naive model continuations.
        if tail and next_chunk.startswith(tail):
            next_chunk = next_chunk[len(tail) :].lstrip("\n")
        full_text = (full_text + "\n" + next_chunk).strip()
        total_input_tokens += int(stream_result.input_tokens or 0)
        total_output_tokens += int(stream_result.output_tokens or 0)

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
        model=CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
        provider="anthropic" if CLAUDE_API_KEY else "openai",
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )
