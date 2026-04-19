from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from app.db import get_pool
from app.repositories import scraped_pages_repository as pages_repo
from app.repositories import crawl_logs_repository as crawl_logs_repo
from app.repositories import onboarding_repository as onboarding_repo
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

def _origin_home(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return str(url or "").strip().rstrip("/")




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
            scrape_error = crawl_logs_repo.extract_error_message(exc)
            page_data = {"url": website_url, "title": "", "meta_description": "",
                         "elements": [], "tech_stack": {}}
            import structlog
            structlog.get_logger().error("onboarding_crawl_gmaps_failed",
                                         url=website_url,
                                         onboarding_id=onboarding_id,
                                         error=scrape_error,
                                         error_type=type(exc).__name__)
            if onboarding_id:
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await crawl_logs_repo.insert_log(
                            conn,
                            onboarding_id=onboarding_id,
                            level="error",
                            source="crawl_task",
                            message=f"Google Maps scrape failed for {website_url}: {scrape_error}",
                            raw={"url": website_url, "error": scrape_error, "error_type": type(exc).__name__},
                        )
                except Exception:
                    pass

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
        async def _on_page_event(event: str, url: str) -> None:
            await send("url", url=url, event=event)

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
                on_page_event=_on_page_event,
            )
        except Exception as exc:
            import structlog
            logger = structlog.get_logger()
            scrape_error = crawl_logs_repo.extract_error_message(exc)
            logger.error("onboarding_crawl_scraper_failed",
                        url=website_url,
                        onboarding_id=onboarding_id,
                        error=scrape_error,
                        error_type=type(exc).__name__,
                        error_repr=repr(exc))
            if onboarding_id:
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await crawl_logs_repo.insert_log(
                            conn,
                            onboarding_id=onboarding_id,
                            level="error",
                            source="crawl_task",
                            message=f"Playwright scrape failed for {website_url}: {scrape_error}",
                            raw={"url": website_url, "error": scrape_error, "error_type": type(exc).__name__},
                        )
                except Exception:
                    pass

        # Fetch the 5 most recent unique scraped pages for this website URL
        # and store their IDs on the onboarding row.
        await send("stage", stage="summarizing", label="Indexing scraped pages")
        pool = get_pool()
        async with pool.acquire() as conn:
            selected_rows = await pages_repo.fetch_recent_unique_by_base_url(
                conn, website_url, limit=5
            )
            # Playwright follows redirects — www.example.com may be stored as example.com.
            # Try the alternate www/non-www variant if we got nothing.
            if not selected_rows:
                parsed_wurl = urlparse(website_url)
                netloc = parsed_wurl.netloc.lower()
                alt_netloc = netloc[4:] if netloc.startswith("www.") else "www." + netloc
                alt_url = f"{parsed_wurl.scheme}://{alt_netloc}"
                selected_rows = await pages_repo.fetch_recent_unique_by_base_url(
                    conn, alt_url, limit=5
                )

        if onboarding_id and selected_rows:
            selected_ids = [int(r["id"]) for r in selected_rows if r.get("id") is not None]
            if selected_ids:
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await onboarding_repo.set_scraped_page_ids(conn, onboarding_id, selected_ids)
                except Exception:
                    pass

        web_summary = f"Website: {website_url}"

    # ── Stage 2: Build business_profile and persist ───────────────────────────
    await send("stage", stage="business_profile", label="Building business profile")

    business_profile = (
        await generate_business_profile(web_summary=web_summary, onboarding_id=onboarding_id)
        if onboarding_id else ""
    )

    # Only persist if we actually got useful content (avoids overwriting good data with fallback)
    if onboarding_id and len(web_summary) > 200:
        await update_onboarding_crawl_outputs(
            onboarding_id,
            web_summary=web_summary,
            business_profile=business_profile,
        )

    return {"web_summary": web_summary, "business_profile": business_profile}