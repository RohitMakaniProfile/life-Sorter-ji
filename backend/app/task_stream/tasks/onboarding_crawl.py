from __future__ import annotations

import time
from typing import Any

from app.task_stream.registry import register_task_stream
from app.utils.url_sanitize import sanitize_http_url
from app.services.onboarding_crawl_service import (
    build_web_summary,
    create_onboarding_skill_call,
    finish_onboarding_skill_call,
    generate_business_profile,
    run_playwright_single_page,
    update_onboarding_crawl_outputs,
)


@register_task_stream("crawl")
async def onboarding_crawl_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Onboarding crawl task (task-stream).

    Replaces the old multi-page crawl_service flow with a focused three-stage pipeline:
      1. Scrape a single page via the scrape-playwright skill.
      2. Build a compact web_summary.
      3. Build a business_profile markdown summary from the web_summary and persist both together.

    Input payload:
      - onboarding_id (carries onboarding_id from task-stream service)
      - user_id     (optional)
      - website_url (required)

    Emits stage events throughout and returns { web_summary, business_profile }.
    """
    raw_url = str(payload.get("website_url") or payload.get("url") or "").strip()
    if not raw_url:
        raise ValueError("website_url is required")

    website_url = sanitize_http_url(raw_url) or raw_url
    onboarding_id = str(payload.get("onboarding_id") or "").strip()

    await send("stage", stage="starting", label="Starting", url=website_url)

    # ── Stage 1: Playwright single-page scrape ────────────────────────────────
    await send("stage", stage="scraping", label="Scraping page", url=website_url)

    skill_call_id: int | None = None
    scrape_started = time.time()

    if onboarding_id:
        skill_call_id = await create_onboarding_skill_call(
            onboarding_session_id=onboarding_id,
            skill_id="scrape-playwright",
            input={"url": website_url, "maxPages": 1},
        )

    page_data: dict[str, Any] = {}
    summary_text: str = ""
    scrape_error: str | None = None


    try:
        async def _on_progress(event: dict[str, Any]) -> None:
            if "url_event" in event:
                await send("url", event=event["url_event"], url=event["url"])
            else:
                await send("stage", **event)

        page_data, summary_text = await run_playwright_single_page(
            url=website_url,
            on_progress=_on_progress,
        )
    except Exception as exc:
        scrape_error = str(exc)
        # Build a minimal stub so the rest of the pipeline can still run
        page_data = {"url": website_url, "title": "", "meta_description": "", "elements": [], "tech_stack": {}}

    if skill_call_id is not None:
        await finish_onboarding_skill_call(
            skill_call_id,
            output=page_data,
            error=scrape_error,
            started_at_ms=scrape_started,
        )

    # ── Stage 2: Build web_summary ───────────────────────────────────────────
    await send("stage", stage="summarizing", label="Building web summary")

    web_summary = (summary_text or "").strip() or build_web_summary(page_data, website_url)

    # ── Stage 3: Build business_profile and persist crawl outputs ────────────
    await send("stage", stage="business_profile", label="Building business profile")

    business_profile = await generate_business_profile(web_summary=web_summary) if onboarding_id else ""


    if onboarding_id:
        await update_onboarding_crawl_outputs(
            onboarding_id,
            web_summary=web_summary,
            business_profile=business_profile,
        )

    return {"web_summary": web_summary, "business_profile": business_profile}
