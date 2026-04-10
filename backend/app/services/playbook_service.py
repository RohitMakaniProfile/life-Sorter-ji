"""
═══════════════════════════════════════════════════════════════
PLAYBOOK SERVICE — Onboarding playbook generation
═══════════════════════════════════════════════════════════════
Single-prompt streaming flow: one LLM call produces context_brief,
website_audit, and playbook sections split by section delimiters.
LLM calls go through OpenRouter (see config for model ids).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.services.ai_helper import ai_helper as _ai

logger = structlog.get_logger()

# ══════════════════════════════════════════════════════════════
#  TOON-STYLE COMPACT SERIALISATION HELPERS
# ══════════════════════════════════════════════════════════════

_SEP = "|"


def _tv(value: Any, sep: str = _SEP) -> str:
    if value is None:
        return "-"
    s = str(value).replace("\n", " ").replace("\r", "").strip()
    return s.replace(sep, ";") if sep in s else s


def _toon_table(label: str, headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header_str = _SEP.join(headers)
    row_lines = [_SEP.join(_tv(cell) for cell in row) for row in rows]
    return f"{label}[{len(rows)}]{{{header_str}}}:\n" + "\n".join(row_lines)


def _toon_inline(label: str, pairs: list[tuple[str, Any]]) -> str:
    parts = [f"{k}:{_tv(v)}" for k, v in pairs if v]
    return f"{label}: " + " | ".join(parts) if parts else ""


def build_tools_toon(all_tools: list[dict[str, Any]]) -> str:
    """Convert a list of tool dicts into a TOON tabular block for the playbook prompt."""
    if not all_tools:
        return ""
    seen: set[str] = set()
    rows: list[list[Any]] = []
    for tool in all_tools:
        name = tool.get("name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        free = tool.get("free")
        price = "Free" if free is True else ("Paid" if free is False else "?")
        rows.append([
            name, tool.get("category", ""), price,
            tool.get("description", ""), tool.get("why_recommended", ""),
            tool.get("issue_solved", ""), tool.get("ease_of_use", ""),
        ])
    return _toon_table("TOOLS", ["name", "type", "price", "desc", "why", "solves", "ease"], rows)


# ══════════════════════════════════════════════════════════════
#  BUILD USER INPUT CONTEXT
# ══════════════════════════════════════════════════════════════

def _build_playbook_input(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: str | dict[str, Any],
    scale_answers: dict[str, Any],
    gap_answers: str = "",
    rca_handoff: str = "",
) -> str:
    label_map = {
        "buying_process": "BuyProcess", "revenue_model": "RevModel",
        "sales_cycle": "SalesCycle", "existing_assets": "Assets",
        "buyer_behavior": "BuyerDiscovery", "current_stack": "Stack",
    }
    parts = [
        f"GOAL: {outcome_label}",
        f"DOMAIN: {domain}",
        (
            f"TASK (PRIMARY FOCUS — THE ENTIRE PLAYBOOK MUST BE BUILT AROUND THIS SPECIFIC TASK): {task}\n"
            f"⚠️ RULE: Every step, every tool, every example must directly serve '{task}'. "
            f"Website/crawl data is background context only — it NEVER changes this task focus."
        ),
    ]
    if business_profile:
        profile_pairs = []
        for key, value in business_profile.items():
            label = label_map.get(key, key.replace("_", " ").title())
            v = ", ".join(value) if isinstance(value, list) else value
            profile_pairs.append((label, v))
        parts.append(_toon_inline("PROFILE", profile_pairs))
    if rca_handoff:
        parts.append(f"\nDIAGNOSTIC_FINDINGS:\n{rca_handoff}")
    elif rca_history:
        rca_rows = [[qa.get("question", ""), qa.get("answer", "")] for qa in rca_history]
        parts.append("\n" + _toon_table("RCA", ["Q", "A"], rca_rows))
    if rca_summary:
        parts.append(f"\nROOT_CAUSE:\n{rca_summary}")
    if isinstance(crawl_summary, str):
        crawl_text = crawl_summary.strip()
        if crawl_text:
            parts.append(f"\nCRAWL:\n{crawl_text}")
    elif isinstance(crawl_summary, dict) and crawl_summary.get("points"):
        pts = crawl_summary["points"]
        parts.append("\nCRAWL[{}]:\n".format(len(pts)) + "\n".join(str(p) for p in pts))
    if gap_answers:
        parts.append(f"\nGAP_ANSWERS:\n{gap_answers}")
    return "\n".join(p for p in parts if p)


# ══════════════════════════════════════════════════════════════
#  SINGLE PROMPT FLOW — One streaming LLM call
#  Prompt fetched from prompts table (slug: "playbook").
#  Output split by section delimiters into context_brief,
#  website_audit, and playbook.
# ══════════════════════════════════════════════════════════════

_SECTION_DELIMITERS = {
    "context_brief": "---SECTION:context_brief---",
    "website_audit": "---SECTION:website_audit---",
    "playbook":      "---SECTION:playbook---",
}


def _split_sections(full_text: str) -> dict[str, str]:
    """
    Split the single-prompt output into 3 sections using delimiters.
    Returns {context_brief, website_audit, playbook} — empty string if section missing.
    """
    sections: dict[str, str] = {"context_brief": "", "website_audit": "", "playbook": ""}

    # Build ordered list of (section_key, delimiter, position)
    positions = []
    for key, delimiter in _SECTION_DELIMITERS.items():
        idx = full_text.find(delimiter)
        if idx != -1:
            positions.append((idx, key, delimiter))
    positions.sort()

    for i, (idx, key, delimiter) in enumerate(positions):
        start = idx + len(delimiter)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(full_text)
        sections[key] = full_text[start:end].strip()

    return sections


async def run_single_prompt_stream(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: str | dict[str, Any],
    recommended_tools: str = "",
    gap_answers: str = "",
    rca_handoff: str = "",
    on_token=None,
) -> dict[str, Any]:
    """
    Single-prompt playbook generation.

    Fetches the system prompt from the prompts table (slug: "playbook"),
    sends one streaming LLM call, and splits the response by section
    delimiters into context_brief, website_audit, and playbook.

    Returns:
        {
            context_brief: str,
            website_audit: str,
            playbook: str,
            latency_ms: int,
            usage: dict,
        }
    """
    from app.services.prompts_service import get_prompt

    system_prompt = await get_prompt("playbook")
    if not system_prompt:
        raise RuntimeError("Prompt slug 'playbook' not found in prompts table")

    user_message = _build_playbook_input(
        outcome_label=outcome_label,
        domain=domain,
        task=task,
        business_profile=business_profile,
        rca_history=rca_history,
        rca_summary=rca_summary,
        crawl_summary=crawl_summary,
        scale_answers=business_profile,
        gap_answers=gap_answers,
        rca_handoff=rca_handoff,
    )
    if recommended_tools:
        user_message += (
            f"\n\n═══ PROVIDED TOOL LIST (use these in TOOL + AI SHORTCUT where relevant) ═══\n"
            f"{recommended_tools}"
        )

    settings = get_settings()
    t0 = time.perf_counter()

    result = await _ai.complete_stream(
        model=settings.OPENROUTER_CLAUDE_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=12000,
        on_token=on_token,
    )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    full_text = result.get("message", "")
    sections = _split_sections(full_text)

    logger.info(
        "Single-prompt playbook stream completed",
        latency_ms=latency_ms,
        has_context_brief=bool(sections["context_brief"]),
        has_website_audit=bool(sections["website_audit"]),
        has_playbook=bool(sections["playbook"]),
    )

    return {
        "context_brief": sections["context_brief"],
        "website_audit": sections["website_audit"],
        "playbook": sections["playbook"],
        "latency_ms": latency_ms,
        "usage": result.get("usage", {}),
    }
