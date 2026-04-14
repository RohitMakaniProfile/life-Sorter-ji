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
from app.skills.service import run_skill, SkillRunResult
from app.skills.summarizer import _summarize_one_page


async def run_scraper(
    *,
    # Required playwright args
    url: str,
    max_pages: int = 5,
    max_depth: int | None = None,
    parallel: bool = True,
    max_parallel_pages: int = 5,
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
    pool = get_pool()
    run_id = f"scrape-playwright-{int(time.time() * 1000)}"
    started_at = datetime.now(timezone.utc)

    args: dict[str, Any] = {
        "url": url,
        "maxPages": max_pages,
        "parallel": parallel,
        "maxParallelPages": max_parallel_pages,
    }
    if max_depth is not None:
        args["maxDepth"] = max_depth
    if skip_urls:
        args["skipUrls"] = [str(u).strip() for u in skip_urls if str(u).strip()]

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

    async def _skill_progress(event: dict[str, Any]) -> None:
        meta: dict[str, Any] = event.get("meta") or {}
        progress_events.append({
            "type": event.get("type", "info"),
            "event": meta.get("event", "info"),
            "message": event.get("message", ""),
            "meta": meta,
            "at": datetime.now(timezone.utc).isoformat(),
        })

    async def _on_page(page: dict[str, Any]) -> None:
        """Called once per page as it arrives. LLM-summarises then stores immediately."""
        markdown = await _summarize_one_page(
            "scrape-playwright",
            page,
            content_field="body_text",
            url_field="url",
            on_progress=_skill_progress,
        )
        async with pool.acquire() as conn:
            await pages_repo.insert_one(
                conn,
                # raw = full page dict; text = LLM markdown
                {"url": page.get("url"), "raw": page, "text": markdown},
                skill_call_id=skill_call_id,
                conversation_id=conversation_id,
                onboarding_id=onboarding_id,
                user_id=user_id,
                message_id=message_id,
            )

    # ── Run the skill ─────────────────────────────────────────────────────────
    result = await run_skill(
        "scrape-playwright",
        message=f"Scrape this website: {url}",
        args=args,
        on_progress=_skill_progress,
        on_page=_on_page,
    )

    # ── Finalize skill_call ───────────────────────────────────────────────────
    duration_ms = int((time.time() - started_at.timestamp()) * 1000)
    output_json = json.dumps(progress_events, ensure_ascii=False)

    if result.status != "ok":
        if skill_call_id is not None:
            async with pool.acquire() as conn:
                if onboarding_id:
                    await skill_calls_repo.finish_onboarding_skill_call(
                        conn, skill_call_id, "error", output_json,
                        str(result.error or "scrape-playwright failed"), duration_ms,
                    )
                else:
                    await skill_calls_repo.update_result(
                        conn, skill_call_id, "error",
                        str(result.error or "scrape-playwright failed"),
                        datetime.now(timezone.utc), duration_ms, output_json,
                    )
        raise RuntimeError(str(result.error or "scrape-playwright failed"))

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