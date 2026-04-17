from __future__ import annotations

import time
import json
from typing import Any
from urllib.parse import urlparse

from app.db import get_pool
from app.repositories import scraped_pages_repository as pages_repo
from app.task_stream.registry import register_task_stream
from app.utils.url_sanitize import sanitize_http_url
from app.services.scraper_service import run_scraper
from app.services.onboarding_crawl_service import (
    build_web_summary,
    create_onboarding_skill_call,
    finish_onboarding_skill_call,
    generate_business_profile,
    is_google_maps_url,
    run_gmaps_serper_skill,
    update_onboarding_crawl_outputs,
)

_LEGAL_URL_HINTS = (
    "/privacy",
    "/terms",
    "/refund",
    "/cancellation",
    "/policy",
)


def _normalize_url(url: str) -> str:
    return (str(url or "").strip().rstrip("/")).lower()


def _origin_home(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return str(url or "").strip().rstrip("/")


def _is_legal_url(url: str) -> bool:
    u = _normalize_url(url)
    return any(hint in u for hint in _LEGAL_URL_HINTS)


def _safe_raw(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _pick_rows_for_summary(rows: list[dict[str, Any]], website_url: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Prefer signal-rich pages for onboarding:
    - force include homepage when available
    - avoid legal/policy pages
    - keep recent ordering from DB query
    """
    if not rows:
        return []

    homepage = _origin_home(website_url)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1) Homepage first (critical for target + CTA extraction)
    for row in rows:
        row_url = str(row.get("url") or _safe_raw(row).get("url") or "")
        norm = _normalize_url(row_url)
        if norm and norm == _normalize_url(homepage):
            picked.append(row)
            seen.add(norm)
            break

    # 2) Non-legal pages with non-empty markdown
    for row in rows:
        row_url = str(row.get("url") or _safe_raw(row).get("url") or "")
        norm = _normalize_url(row_url)
        if not norm or norm in seen:
            continue
        markdown = str(row.get("markdown") or "").strip()
        if not markdown:
            continue
        if _is_legal_url(row_url):
            continue
        picked.append(row)
        seen.add(norm)
        if len(picked) >= limit:
            return picked

    # 3) Fallback: allow legal pages if not enough content pages
    for row in rows:
        row_url = str(row.get("url") or _safe_raw(row).get("url") or "")
        norm = _normalize_url(row_url)
        if not norm or norm in seen:
            continue
        markdown = str(row.get("markdown") or "").strip()
        if not markdown:
            continue
        picked.append(row)
        seen.add(norm)
        if len(picked) >= limit:
            break
    return picked


@register_task_stream("crawl")
async def onboarding_crawl_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Onboarding crawl task (task-stream).

    For regular URLs:
      1. run_scraper — creates skill_call row, scrapes, LLM-summarises each page,
         stores raw + markdown in scraped_pages one by one.
      2. Fetch the 5 most recently stored pages for this URL from scraped_pages.
      3. Join their markdown as web_summary.
      4. Generate business_profile from web_summary and persist both.

    For Google Maps URLs the existing gmaps-serper skill path is unchanged.

    Input payload:
      - onboarding_id  (optional)
      - user_id        (optional)
      - website_url    (required)
    """
    raw_url = str(payload.get("website_url") or payload.get("url") or "").strip()
    if not raw_url:
        raise ValueError("website_url is required")

    website_url = sanitize_http_url(raw_url) or raw_url
    onboarding_id = str(payload.get("onboarding_id") or "").strip() or None

    await send("stage", stage="starting", label="Starting", url=website_url)

    # ── Stage 1: Scrape ───────────────────────────────────────────────────────
    gmaps = is_google_maps_url(website_url)
    await send("stage", stage="scraping",
               label="Fetching Google Maps data" if gmaps else "Scraping page",
               url=website_url)

    web_summary = ""
    scrape_error: str | None = None

    if gmaps:
        # ── Google Maps path (unchanged) ──────────────────────────────────────
        skill_call_id: int | None = None
        scrape_started = time.time()

        if onboarding_id:
            skill_call_id = await create_onboarding_skill_call(
                onboarding_session_id=onboarding_id,
                skill_id="gmaps-serper",
                input={"url": website_url},
            )

        page_data: dict[str, Any] = {}
        summary_text = ""

        try:
            async def _on_gmaps_progress(event: dict[str, Any]) -> None:
                if "url_event" in event:
                    await send("url", event=event["url_event"], url=event["url"])
                else:
                    await send("stage", **event)

            page_data, summary_text = await run_gmaps_serper_skill(
                url=website_url,
                on_progress=_on_gmaps_progress,
            )
        except Exception as exc:
            scrape_error = str(exc)
            page_data = {"url": website_url, "title": "", "meta_description": "",
                         "elements": [], "tech_stack": {}}

        if skill_call_id is not None:
            await finish_onboarding_skill_call(
                skill_call_id,
                output=page_data,
                error=scrape_error,
                started_at_ms=scrape_started,
            )

        web_summary = summary_text.strip() or build_web_summary(page_data, website_url)

    else:
        # ── Playwright path via run_scraper ───────────────────────────────────
        # run_scraper creates and finalizes the skill_call row internally.
        try:
            await run_scraper(
                url=website_url,
                max_pages=5,
                parallel=True,
                skip_urls=[
                    f"{_origin_home(website_url)}/privacy",
                    f"{_origin_home(website_url)}/terms",
                    f"{_origin_home(website_url)}/refund",
                ],
                onboarding_id=onboarding_id,
            )
        except RuntimeError as exc:
            import structlog
            logger = structlog.get_logger()
            scrape_error = str(exc)
            logger.error("onboarding_crawl_scraper_failed",
                        url=website_url,
                        onboarding_id=onboarding_id,
                        error=scrape_error,
                        error_type=type(exc).__name__,
                        error_repr=repr(exc))

        # Fetch recent rows and pick summary pages:
        # homepage + non-legal content pages first.
        await send("stage", stage="summarizing", label="Building web summary")
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await pages_repo.find_by_base_url(conn, website_url, limit=30)

        selected_rows = _pick_rows_for_summary(rows, website_url, limit=5)

        parts = [
            str(row["markdown"] or "").strip()
            for row in selected_rows
            if str(row.get("markdown") or "").strip()
        ]
        web_summary = "\n\n".join(parts) if parts else f"Website: {website_url}"

    # ── Stage 2: Build business_profile and persist ───────────────────────────
    await send("stage", stage="business_profile", label="Building business profile")

    business_profile = (
        await generate_business_profile(web_summary=web_summary, onboarding_id=onboarding_id)
        if onboarding_id else ""
    )

    if onboarding_id:
        await update_onboarding_crawl_outputs(
            onboarding_id,
            web_summary=web_summary,
            business_profile=business_profile,
        )

    return {"web_summary": web_summary, "business_profile": business_profile}