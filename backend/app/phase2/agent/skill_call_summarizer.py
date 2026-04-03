from __future__ import annotations

import json
from typing import Any

from app.services.ai_helper import ai_helper as _ai


async def build_calls_summary(skill_calls: list[dict[str, Any]]) -> str:
    """
    Build a compact routing summary over recent skill calls.
    Used by the skill selector to decide which skills to run next.
    """
    if not skill_calls:
        return "(none yet)"

    recent = skill_calls[-8:]

    try:
        result = await _ai.chat(
            message="\n".join([
                "Summarize prior tool/skill calls for routing the NEXT skill.",
                "Requirements:",
                "- Output 8-15 bullet points.",
                "- Include which skills ran, key parameters (url/platform), counts (pages/reviews), and notable failures.",
                "- Do NOT include long excerpts of raw outputs.",
                "- Do NOT invent anything.",
                "",
                "SKILL CALLS (JSON):",
                json.dumps(recent, ensure_ascii=False)[:120_000],
            ]),
            system_prompt="You produce faithful, compact summaries for downstream routing.",
        )
        text = result.message.strip()
        return text or "(none yet)"
    except Exception:
        return "\n".join(
            f"- {c.get('skillId', '?')}: {c.get('status', '?')} ({c.get('durationMs', 0)}ms)"
            for c in recent
        )
