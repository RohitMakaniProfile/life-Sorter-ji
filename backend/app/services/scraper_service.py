"""
services/scraper_service.py
============================
Orchestrates a scrape-playwright skill run and persists results to the DB.

Responsibilities:
- Accept optional context (onboarding_id, conversation_id, message_id, user_id)
  and required playwright args (url, max_pages, max_depth, …).
- Create a skill_calls row before streaming begins.
- Pass an on_page callback to run_skill so each page is processed as it arrives:
    * LLM-summarise the page immediately (raw → markdown).
    * Insert raw + markdown into scraped_pages one at a time.
- All progress/info events are collected and stored in skill_calls.output.
- Pages are never present in the final SkillRunResult — only in DB.
- Finalize the skill_calls row (state, output, duration_ms).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from app.db import get_pool
from app.repositories import scraped_pages_repository as pages_repo
from app.repositories import skill_calls_repository as skill_calls_repo
from app.repositories import crawl_logs_repository as crawl_logs_repo
from app.skills.service import run_skill, SkillRunResult
from app.skills.summarizer import _summarize_one_page


async def run_scraper(
    *,
    # Required playwright args
    url: str,
    max_pages: int = 5,
    max_depth: int | None = None,
    parallel: bool = True,
    skip_urls: list[str] | None = None,
    # Optional context — all may be None
    onboarding_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
    user_id: str | None = None,
) -> SkillRunResult:
    """
    Run the scrape-playwright skill.

    Each page is LLM-summarised and stored in scraped_pages immediately as it
    arrives via the on_page callback — never buffered or returned in the result.

    At least one of (onboarding_id, conversation_id) should be provided for a
    skill_calls row to be created; if neither is available the scrape still runs
    and pages are stored without a skill_call_id link.

    Raises RuntimeError if the skill returns a non-ok status.
    """
    import structlog
    logger = structlog.get_logger()

    pool = get_pool()
    run_id = f"scrape-playwright-{int(time.time() * 1000)}"
    started_at = datetime.now(timezone.utc)

    args: dict[str, Any] = {
        "url": url,
        "maxPages": max_pages,
        "parallel": parallel,
    }
    if max_depth is not None:
        args["maxDepth"] = max_depth
    if skip_urls:
        args["skipUrls"] = [str(u).strip() for u in skip_urls if str(u).strip()]

    logger.info("run_scraper_starting",
               url=url,
               max_pages=max_pages,
               parallel=parallel,
               max_depth=max_depth,
               skip_urls_count=len(skip_urls) if skip_urls else 0,
               onboarding_id=onboarding_id,
               args=args)

    input_json = json.dumps({"url": url, "args": args}, ensure_ascii=False)

    # ── Create skill_call row ─────────────────────────────────────────────────
    skill_call_id: int | None = None

    async with pool.acquire() as conn:
        if onboarding_id:
            skill_call_id = await skill_calls_repo.insert_onboarding_skill_call(
                conn,
                onboarding_id,
                "scrape-playwright",
                run_id,
                input_json,
            )
        elif conversation_id and message_id:
            raw_id = await skill_calls_repo.insert_returning_id(
                conn,
                conversation_id,
                message_id,
                "scrape-playwright",
                run_id,
                input_json,
                started_at,
            )
            skill_call_id = int(raw_id)

    # ── Callbacks ─────────────────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []
    page_count = 0

    async def _skill_progress(event: dict[str, Any]) -> None:
        meta: dict[str, Any] = event.get("meta") or {}
        event_type = meta.get("event", "info")
        progress_events.append({
            "type": event.get("type", "info"),
            "event": event_type,
            "message": event.get("message", ""),
            "meta": meta,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        # Log important events
        if event_type in ["page_data", "discovered", "started", "checkpoint"]:
            logger.info("scraper_progress_event",
                       event_type=event_type,
                       url=meta.get("url"),
                       message=event.get("message", "")[:200])

    async def _on_page(page: dict[str, Any]) -> None:
        """Called once per page as it arrives. LLM-summarises then stores immediately."""
        nonlocal page_count
        page_count += 1
        page_url = page.get("url", "unknown")

        logger.info("scraper_page_callback",
                   page_number=page_count,
                   url=page_url,
                   onboarding_id=onboarding_id)

        page_error: str | None = None
        page_status: str = "done"
        markdown: str = ""

        try:
            markdown = await _summarize_one_page(
                "scrape-playwright",
                page,
                content_field="body_text",
                url_field="url",
                on_progress=_skill_progress,
            )
            logger.info("scraper_page_summarized",
                       page_number=page_count,
                       url=page_url,
                       markdown_length=len(markdown))
        except Exception as exc:
            page_error = crawl_logs_repo.extract_error_message(exc)
            page_status = "error"
            logger.error("scraper_page_summarize_failed",
                        page_number=page_count,
                        url=page_url,
                        error=page_error,
                        error_type=type(exc).__name__)
            if onboarding_id:
                try:
                    async with pool.acquire() as conn:
                        await crawl_logs_repo.insert_log(
                            conn,
                            onboarding_id=onboarding_id,
                            user_id=user_id,
                            level="error",
                            source="summarizer",
                            message=f"Failed to summarize page {page_url}: {page_error}",
                            raw={"url": page_url, "error": page_error, "error_type": type(exc).__name__},
                        )
                except Exception:
                    pass

        async with pool.acquire() as conn:
            await pages_repo.insert_one(
                conn,
                {"url": page.get("url"), "raw": page, "text": markdown},
                skill_call_id=skill_call_id,
                conversation_id=conversation_id,
                onboarding_id=onboarding_id,
                user_id=user_id,
                message_id=message_id,
                crawl_status=page_status,
                error=page_error,
            )

        logger.info("scraper_page_stored",
                   page_number=page_count,
                   url=page_url,
                   skill_call_id=skill_call_id,
                   status=page_status)

    # ── Run the skill ─────────────────────────────────────────────────────────
    logger.info("run_scraper_executing_skill", url=url)

    result = await run_skill(
        "scrape-playwright",
        message=f"Scrape this website: {url}",
        args=args,
        on_progress=_skill_progress,
        on_page=_on_page,
    )

    logger.info("run_scraper_skill_completed",
               url=url,
               status=result.status,
               page_count=page_count,
               progress_events_count=len(progress_events),
               result_data_keys=list(result.data.keys()) if isinstance(result.data, dict) else None)

    # ── Finalize skill_call ───────────────────────────────────────────────────
    duration_ms = int((time.time() - started_at.timestamp()) * 1000)
    output_json = json.dumps(progress_events, ensure_ascii=False)

    if result.status != "ok":
        error_detail = result.error
        error_str = crawl_logs_repo.extract_error_message(error_detail) or "scrape-playwright failed"

        logger.error("scraper_skill_failed",
                    skill_id="scrape-playwright",
                    url=url,
                    error=error_str,
                    error_type=type(error_detail).__name__ if error_detail else None,
                    error_repr=repr(error_detail) if error_detail else None,
                    result_status=result.status,
                    result_data=str(result.data)[:500] if result.data else None,
                    skill_call_id=skill_call_id)

        if onboarding_id:
            try:
                async with pool.acquire() as conn:
                    await crawl_logs_repo.insert_log(
                        conn,
                        onboarding_id=onboarding_id,
                        user_id=user_id,
                        level="error",
                        source="scraper",
                        message=f"Scraper failed for {url}: {error_str}",
                        raw={
                            "url": url,
                            "error": error_str,
                            "result_status": result.status,
                            "result_data": str(result.data)[:500] if result.data else None,
                        },
                    )
            except Exception:
                pass

        if skill_call_id is not None:
            async with pool.acquire() as conn:
                if onboarding_id:
                    await skill_calls_repo.finish_onboarding_skill_call(
                        conn, skill_call_id, "error", output_json,
                        error_str, duration_ms,
                    )
                else:
                    await skill_calls_repo.update_result(
                        conn, skill_call_id, "error",
                        error_str,
                        datetime.now(timezone.utc), duration_ms, output_json,
                    )
        raise RuntimeError(error_str)

    if skill_call_id is not None:
        async with pool.acquire() as conn:
            if onboarding_id:
                await skill_calls_repo.finish_onboarding_skill_call(
                    conn, skill_call_id, "done", output_json, None, duration_ms,
                )
            else:
                await skill_calls_repo.update_result(
                    conn, skill_call_id, "done", None,
                    datetime.now(timezone.utc), duration_ms, output_json,
                )

    return result