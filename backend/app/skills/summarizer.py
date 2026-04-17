from __future__ import annotations

from typing import Any

from app.config import OPENAI_MODEL, get_settings
from app.services.ai_helper import ai_helper as _ai
from .models import ProgressCb
from .utils import _get_by_path, _clean_text


def _extract_page_content(item: dict[str, Any], content_field: str) -> str:
    """
    Build robust page content text for summarization across scraper schemas.
    Priority:
      1) explicit content field / text / snapshot / body_text
      2) element-level content extracted by scraper
      3) title + meta_description fallback
    """
    import json as _json

    raw_content = (
        item.get(content_field)
        or item.get("text")
        or item.get("snapshot")
        or item.get("body_text")
        or ""
    )
    if isinstance(raw_content, (dict, list)):
        raw_content = _json.dumps(raw_content, ensure_ascii=False)
    text = _clean_text(str(raw_content))
    if text:
        return text

    # Fallback for crawler payloads that keep most text inside elements[].
    elements = item.get("elements")
    if isinstance(elements, list) and elements:
        lines: list[str] = []
        for el in elements:
            if not isinstance(el, dict):
                continue
            et = str(el.get("type") or "").strip()
            content = _clean_text(str(el.get("content") or ""))
            if not content:
                continue
            lines.append(f"{et}: {content}" if et else content)
            if len(lines) >= 120:
                break
        if lines:
            return "\n".join(lines)

    title = _clean_text(str(item.get("title") or ""))
    desc = _clean_text(str(item.get("meta_description") or ""))
    fallback = "\n".join([v for v in [title, desc] if v]).strip()
    return fallback


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


def _build_page_content(item: dict[str, Any], content_field: str) -> str:
    """
    Build a rich, structured content string from a scraped page dict.

    Uses all available fields — title, meta, structured elements (headings /
    paragraphs), body text, internal links, schema types, and tech signals
    inferred from network requests — so the LLM receives the full picture.
    """
    import json as _json

    parts: list[str] = []

    # ── 1. Meta ──────────────────────────────────────────────────────────────
    title = _clean_text(str(item.get("title") or ""))
    meta_desc = _clean_text(str(item.get("meta_description") or ""))
    meta_kw = _clean_text(str(item.get("meta_keywords") or ""))
    if title:
        parts.append(f"Title: {title}")
    if meta_desc:
        parts.append(f"Meta Description: {meta_desc}")
    if meta_kw:
        parts.append(f"Meta Keywords: {meta_kw}")

    # ── 2. Structured elements (headings + paragraphs) ───────────────────────
    elements = item.get("elements") or []
    if isinstance(elements, list):
        headings: list[str] = []
        paragraphs: list[str] = []
        for el in elements:
            if not isinstance(el, dict):
                continue
            etype = str(el.get("type") or "").lower()
            econtent = _clean_text(str(el.get("content") or ""))
            if not econtent:
                continue
            if etype in ("h1", "h2", "h3", "h4", "h5", "h6"):
                headings.append(f"[{etype.upper()}] {econtent}")
            elif etype == "p":
                paragraphs.append(econtent)
        if headings:
            parts.append("\nHeadings:\n" + "\n".join(headings))
        if paragraphs:
            # cap paragraphs to avoid blowing the token budget
            para_block = " | ".join(paragraphs[:60])
            parts.append(f"\nParagraphs:\n{para_block[:6_000]}")

    # ── 3. Body text (primary content field) ─────────────────────────────────
    raw_content = (
        item.get(content_field)
        or item.get("text")
        or item.get("snapshot")
        or item.get("body_text")
        or ""
    )
    if isinstance(raw_content, (dict, list)):
        raw_content = _json.dumps(raw_content, ensure_ascii=False)
    body = _clean_text(str(raw_content))
    if body:
        parts.append(f"\nBody Text:\n{body[:10_000]}")

    # ── 4. Internal links ─────────────────────────────────────────────────────
    internal = item.get("links_internal") or []
    if isinstance(internal, list) and internal:
        parts.append("\nInternal Links:\n" + "\n".join(str(u) for u in internal[:30]))

    # ── 5. Schema types ───────────────────────────────────────────────────────
    schemas = item.get("schema_types") or []
    if isinstance(schemas, list) and schemas:
        parts.append("Schema Markup: " + ", ".join(str(s) for s in schemas))

    # ── 6. Tech signals from network requests ────────────────────────────────
    network = item.get("network_requests") or []
    if isinstance(network, list) and network:
        tech_signals: list[str] = []
        checks = [
            ("analytics.google.com", "Google Analytics"),
            ("googletagmanager", "Google Tag Manager"),
            ("firebase", "Firebase"),
            ("sentry", "Sentry"),
            ("clarity.ms", "Microsoft Clarity"),
            ("penpencil", "PenPencil API"),
            ("unleash", "Unleash (feature flags)"),
            ("hotjar", "Hotjar"),
            ("intercom", "Intercom"),
            ("stripe", "Stripe"),
        ]
        for pattern, label in checks:
            if any(pattern in str(r) for r in network):
                tech_signals.append(label)
        if tech_signals:
            parts.append("Tech Stack (from network): " + ", ".join(tech_signals))

    # ── 7. Images (CDN / count) ───────────────────────────────────────────────
    images = item.get("image_urls") or []
    if isinstance(images, list) and images:
        cdns = set()
        from urllib.parse import urlparse as _up
        for img in images:
            try:
                cdns.add(_up(str(img)).netloc)
            except Exception:
                pass
        parts.append(f"Images: {len(images)} total, CDNs: {', '.join(sorted(cdns))}")

    return "\n".join(parts)


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
    Builds a rich structured content string from all available fields so the
    LLM has the full picture and preserves details faithfully.
    Returns the markdown string (or the raw body text if the LLM fails).
    """
    page_url = str(item.get(url_field) or "")
    page_content = _build_page_content(item, content_field)[:14_000]
    if not page_content:
        return ""

    prompt = "\n".join([
        f"Skill: {skill_id}",
        f"Page URL: {page_url}",
        "Convert the structured page data below into detailed, faithful Markdown notes.",
        "Rules:",
        "- Preserve ALL facts: titles, descriptions, headings, program details, people, links, tech signals, image info.",
        "- Use bullet points and sections to organise the information clearly.",
        "- Remove only pure duplication (e.g. repeated image alt texts).",
        "- Do NOT invent or omit data. More detail is better than less.",
        "",
        "Page data:",
        page_content,
    ])
    try:
        res = await _ai.chat(
            prompt,
            system_prompt=(
                "You are a precise webpage data extractor. "
                "Your job is to convert structured page data into detailed Markdown notes "
                "that preserve every meaningful fact. Do not compress or omit information."
            ),
            temperature=0.1,
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
        page_content = _build_page_content(item, content_field) if isinstance(item, dict) else _clean_text(str(item.get(content_field) or ""))[:20_000]
        if not page_content:
            continue
        prompt = "\n".join([
            f"Skill: {skill_id}",
            f"Page URL: {page_url}",
            "Convert the structured page data below into detailed, faithful Markdown notes.",
            "Rules:",
            "- Preserve ALL facts: titles, descriptions, headings, program details, people, links, tech signals.",
            "- Use bullet points and sections to organise the information clearly.",
            "- Remove only pure duplication (e.g. repeated image alt texts).",
            "- Do NOT invent or omit data. More detail is better than less.",
            "",
            "Page data:",
            page_content,
        ])
        try:
            res = await _ai.chat(
                prompt,
                system_prompt=(
                    "You are a precise webpage data extractor. "
                    "Your job is to convert structured page data into detailed Markdown notes "
                    "that preserve every meaningful fact. Do not compress or omit information."
                ),
                temperature=0.1,
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
        page_content = _build_page_content(item, content_field) if isinstance(item, dict) else _clean_text(str(item.get(content_field) or ""))[:20_000]
        if not page_content:
            continue
        prompt = "\n".join([
            f"Skill: {skill_id}",
            f"Page URL: {page_url}",
            "Convert the structured page data below into detailed, faithful Markdown notes.",
            "Rules:",
            "- Preserve ALL facts: titles, descriptions, headings, program details, people, links, tech signals.",
            "- Use bullet points and sections to organise the information clearly.",
            "- Remove only pure duplication (e.g. repeated image alt texts).",
            "- Do NOT invent or omit data. More detail is better than less.",
            "",
            "Page data:",
            page_content,
        ])
        try:
            res = await _ai.chat(
                prompt,
                system_prompt=(
                    "You are a precise webpage data extractor. "
                    "Your job is to convert structured page data into detailed Markdown notes "
                    "that preserve every meaningful fact. Do not compress or omit information."
                ),
                temperature=0.1,
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

