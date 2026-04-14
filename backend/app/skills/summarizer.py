from __future__ import annotations

from typing import Any

from app.config import OPENAI_MODEL, get_settings
from app.services.ai_helper import ai_helper as _ai
from .models import ProgressCb
from .utils import _get_by_path, _clean_text


async def _emit_summary_token_usage(
    on_progress: ProgressCb | None,
    *,
    stage: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    if on_progress is None:
        return
    settings = get_settings()
    active_model = (settings.OPENROUTER_MODEL or OPENAI_MODEL).strip()
    try:
        await on_progress(
            {
                "stage": "running",
                "type": "task",
                "message": f"Token usage recorded ({stage})",
                "meta": {
                    "kind": "token-usage",
                    "stage": stage,
                    "provider": "openrouter",
                    "model": active_model,
                    "inputTokens": int(input_tokens or 0),
                    "outputTokens": int(output_tokens or 0),
                },
            }
        )
    except Exception:
        pass


async def _summarize_one_page(
    skill_id: str,
    item: dict[str, Any],
    *,
    content_field: str = "snapshot",
    url_field: str = "url",
    on_progress: ProgressCb | None = None,
) -> str:
    """
    LLM-summarise a single scraped page dict immediately as it arrives.
    Tries content_field first, then "text", then "snapshot" as fallbacks.
    Returns the markdown string (or the raw content if LLM fails).
    """
    import json as _json
    page_url = str(item.get(url_field) or "")
    raw_content = (
        item.get(content_field)
        or item.get("text")
        or item.get("snapshot")
        or ""
    )
    if isinstance(raw_content, (dict, list)):
        raw_content = _json.dumps(raw_content, ensure_ascii=False)
    page_content = _clean_text(str(raw_content))[:14_000]
    if not page_content:
        return ""

    prompt = "\n".join([
        f"Skill: {skill_id}",
        f"Page URL: {page_url}",
        "Rewrite the page content into concise natural language, preserving all key information and removing redundant words/repetition.",
        "Do not invent data. Keep it compact and faithful.",
        "",
        "Page content:",
        page_content,
    ])
    try:
        res = await _ai.chat(
            prompt,
            system_prompt="You compress webpage extraction text into faithful natural-language notes.",
            temperature=0.2,
            provider="openai",
        )
        await _emit_summary_token_usage(
            on_progress,
            stage=f"skill-summary.{skill_id}.page",
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
        )
        return (res.message or "").strip()
    except Exception:
        return page_content


async def _summarize_single(
    skill_id: str,
    data: Any,
    fallback_text: str,
    *,
    on_progress: ProgressCb | None = None,
) -> str:
    from .utils import _json_dumps
    try:
        raw_json = _json_dumps(data)
    except Exception:
        return fallback_text
    raw_json = raw_json[:120_000]
    prompt = "\n".join([
        f"Skill: {skill_id}",
        "Convert this raw JSON output into compact, faithful natural-language Markdown.",
        "Rules:",
        "- Preserve all information categories/keys at least once.",
        "- Remove repetitive wording and duplicate entries.",
        "- For long arrays, summarize with counts and representative examples.",
        "- Do not invent data.",
        "",
        "Raw JSON:",
        raw_json,
    ])
    res = await _ai.chat(
        prompt,
        system_prompt="You are a precise data-to-text formatter. Keep full coverage with minimal redundancy.",
        temperature=0.2,
    )
    await _emit_summary_token_usage(
        on_progress,
        stage=f"skill-summary.{skill_id}",
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
    )
    return (res.message or "").strip() or fallback_text


async def _summarize_multi_page(
    skill_id: str,
    data: Any,
    *,
    array_path: str | None,
    content_field: str,
    url_field: str,
    fallback_text: str,
    on_progress: ProgressCb | None = None,
) -> str:
    pages = _get_by_path(data, array_path)
    if not isinstance(pages, list) or not pages:
        return await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)

    blocks: list[str] = []
    for idx, item in enumerate(pages, start=1):
        if not isinstance(item, dict):
            continue
        page_url = str(item.get(url_field) or f"(page {idx})")
        page_content = _clean_text(str(item.get(content_field) or ""))[:14_000]
        if not page_content:
            continue
        prompt = "\n".join([
            f"Skill: {skill_id}",
            f"Page URL: {page_url}",
            "Rewrite the page content into concise natural language, preserving all key information and removing redundant words/repetition.",
            "Do not invent data. Keep it compact and faithful.",
            "",
            "Page content:",
            page_content,
        ])
        try:
            res = await _ai.chat(
                prompt,
                system_prompt="You compress webpage extraction text into faithful natural-language notes.",
                temperature=0.2,
            )
            await _emit_summary_token_usage(
                on_progress,
                stage=f"skill-summary.{skill_id}.page",
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
            )
            page_summary = (res.message or "").strip()
        except Exception:
            page_summary = page_content
        if page_summary:
            blocks.append(f"page: {page_url}\ncontent: {page_summary}")

    if not blocks:
        return await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)
    return "\n\n".join(blocks)


async def _summarize_multi_page_entries(
    skill_id: str,
    data: Any,
    *,
    array_path: str | None,
    content_field: str,
    url_field: str,
    fallback_text: str,
    on_progress: ProgressCb | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Same as _summarize_multi_page but also returns per-page entries
    {url, raw, text} so they can be written to scraped_pages.
    """
    pages = _get_by_path(data, array_path)
    if not isinstance(pages, list) or not pages:
        return [], await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)

    entries: list[dict[str, Any]] = []
    blocks: list[str] = []

    for idx, item in enumerate(pages, start=1):
        if not isinstance(item, dict):
            continue
        page_url = str(item.get(url_field) or f"(page {idx})")
        page_content = _clean_text(str(item.get(content_field) or ""))[:14_000]
        if not page_content:
            continue
        prompt = "\n".join([
            f"Skill: {skill_id}",
            f"Page URL: {page_url}",
            "Rewrite the page content into concise natural language, preserving all key information and removing redundant words/repetition.",
            "Do not invent data. Keep it compact and faithful.",
            "",
            "Page content:",
            page_content,
        ])
        try:
            res = await _ai.chat(
                prompt,
                system_prompt="You compress webpage extraction text into faithful natural-language notes.",
                temperature=0.2,
                provider="openai",
            )
            await _emit_summary_token_usage(
                on_progress,
                stage=f"skill-summary.{skill_id}.page",
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
            )
            page_summary = (res.message or "").strip()
        except Exception:
            page_summary = page_content

        if page_summary:
            entries.append({"url": page_url, "raw": item, "text": page_summary})
            blocks.append(f"page: {page_url}\ncontent: {page_summary}")

    if not blocks:
        return [], await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)
    return entries, "\n\n".join(blocks)

