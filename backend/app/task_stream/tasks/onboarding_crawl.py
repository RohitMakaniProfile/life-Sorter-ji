from __future__ import annotations

import time
from typing import Any

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
                max_parallel_pages=5,
                onboarding_id=onboarding_id,
            )
        except RuntimeError as exc:
            scrape_error = str(exc)

        # Fetch the 5 most recently stored pages for this URL and join markdown.
        await send("stage", stage="summarizing", label="Building web summary")
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await pages_repo.find_by_base_url(conn, website_url, limit=5)

        parts = [
            str(row["markdown"] or "").strip()
            for row in rows
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