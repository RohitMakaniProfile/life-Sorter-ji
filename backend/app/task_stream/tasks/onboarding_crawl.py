from __future__ import annotations

import time
from typing import Any

from app.task_stream.registry import register_task_stream
from app.utils.url_sanitize import sanitize_http_url
from app.services.onboarding_crawl_service import (
    build_web_summary,
    create_onboarding_skill_call,
    fetch_onboarding_context,
    finish_onboarding_skill_call,
    generate_rca_questions,
    run_playwright_single_page,
    update_onboarding_rca_questions,
    update_onboarding_web_summary,
)


@register_task_stream("crawl")
async def onboarding_crawl_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Onboarding crawl task (task-stream).

    Replaces the old multi-page crawl_service flow with a focused three-stage pipeline:
      1. Scrape a single page via the scrape-playwright skill.
      2. Build a compact web_summary and persist it to onboarding.
      3. Generate up to 3 RCA questions and persist them to onboarding.rca_qa.

    Input payload:
      - session_id  (injected by task-stream service)
      - user_id     (optional)
      - website_url (required)

    Emits stage events throughout and returns { web_summary, rca_questions }.
    """
    raw_url = str(payload.get("website_url") or payload.get("url") or "").strip()
    if not raw_url:
        raise ValueError("website_url is required")

    website_url = sanitize_http_url(raw_url) or raw_url
    session_id = str(payload.get("session_id") or "").strip()

    await send("stage", stage="starting", label="Starting", url=website_url)

    # ── Stage 1: Playwright single-page scrape ────────────────────────────────
    await send("stage", stage="scraping", label="Scraping page", url=website_url)

    skill_call_id: int | None = None
    scrape_started = time.time()

    if session_id:
        skill_call_id = await create_onboarding_skill_call(
            onboarding_session_id=session_id,
            skill_id="scrape-playwright",
            input={"url": website_url, "maxPages": 1},
        )

    page_data: dict[str, Any] = {}
    summary_text: str = ""
    scrape_error: str | None = None

    try:
        async def _on_progress(event: dict[str, Any]) -> None:
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

    # ── Stage 2: Build and persist web_summary ───────────────────────────────
    await send("stage", stage="summarizing", label="Building web summary")

    web_summary = (summary_text or "").strip() or build_web_summary(page_data, website_url)

    if session_id:
        await update_onboarding_web_summary(session_id, web_summary)

    # ── Stage 3: Generate RCA questions ──────────────────────────────────────
    await send("stage", stage="generating_questions", label="Generating RCA questions")

    rca_questions: list[dict[str, Any]] = []

    if session_id:
        onboarding = await fetch_onboarding_context(session_id)
        rca_questions = await generate_rca_questions(
            outcome=onboarding.get("outcome", ""),
            domain=onboarding.get("domain", ""),
            task=onboarding.get("task", ""),
            web_summary=web_summary,
            scale_answers=onboarding.get("scale_answers") or {},
            max_questions=3,
        )
        if rca_questions:
            await update_onboarding_rca_questions(session_id, rca_questions)

    return {"web_summary": web_summary, "rca_questions": rca_questions}
