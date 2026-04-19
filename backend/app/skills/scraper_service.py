"""
scraper_service.py
==================
All Playwright-specific logic for the scrape-playwright skill.

Responsibilities:
- Stream the remote scraper microservice (SCRAPER_BASE_URL).
- Merge previously scraped pages (from scraped_pages table) so only new URLs
  are fetched.
- After a successful run, persist every scraped page to the `scraped_pages`
  table (url / raw / markdown).  The orchestrator's skill_calls row stores
  only non-page events (progress metadata + final result summary) keeping
  skill_calls.output lean.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx

from app.db import get_pool
from app.repositories import scraped_pages_repository as pages_repo
from .models import PageCb, ProgressCb, SkillRunResult
from .utils import _emit, _extract_url, _extract_json_objects_from_text, _progress_stream_kind


def _is_homepage_scrape(args: dict[str, Any] | None) -> bool:
    """Return True when scraping only the root page (maxPages <= 1)."""
    if not isinstance(args, dict):
        return False
    return int(args.get("maxPages") or 0) <= 1


async def _load_existing_pages(base_url: str) -> tuple[list[dict[str, Any]], list[int]]:
    """
    Return pages previously stored in scraped_pages for this origin so they
    can be merged with new results and skipped during crawling.
    Returns (pages_data, page_ids) tuple.
    """
    from urllib.parse import urlparse
    try:
        p = urlparse(str(base_url or "").strip())
        origin = f"{p.scheme.lower()}://{p.netloc.lower()}" if p.scheme and p.netloc else ""
    except Exception:
        origin = ""
    if not origin:
        return [], []

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await pages_repo.find_by_base_url(conn, origin)

    pages: list[dict[str, Any]] = []
    page_ids: list[int] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row["url"] or "").strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        # Re-inflate raw back to dict when possible (stored as JSON text)
        raw_val: Any = row["raw"] or ""
        try:
            raw_val = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
        except Exception:
            pass
        pages.append({
            "url": row["url"],
            "raw": raw_val,
            "text": row["markdown"] or "",
            "title": row["page_title"] or "",
        })
        # Also collect the page ID
        if row.get("id") is not None:
            page_ids.append(int(row["id"]))
    return pages, page_ids



async def _route_page_or_progress(
    item: dict[str, Any],
    *,
    on_page: PageCb | None,
    on_progress: ProgressCb | None,
    existing_urls: set[str],
    seen_in_stream: set[str],
) -> None:
    """
    Route a single SSE event item to on_page (page content) or on_progress (metadata).

    When on_page is provided and this item carries page content (streamKind=="data"):
    - call on_page for new, unseen URLs only
    - emit a lightweight progress event with just the URL (no content)

    Otherwise forward the event to on_progress as-is.
    """
    if on_page is not None and item.get("streamKind") == "data":
        page_url = str(item.get("url") or "").strip().rstrip("/")
        if page_url and page_url not in existing_urls and page_url not in seen_in_stream:
            seen_in_stream.add(page_url)
            # Synthesize discovered + scraping so the UI shows the URL before summarizing fires
            for evt in ("discovered", "scraping"):
                await _emit(on_progress, {
                    "stage": "running", "type": "info",
                    "message": page_url,
                    "meta": {"event": evt, "url": page_url, "streamKind": "info"},
                })
            await on_page(item)
        # Always emit lightweight progress for tracking
        await _emit(on_progress, {
            "stage": "running", "type": "info",
            "message": str(item.get("url") or "page scraped"),
            "meta": {"event": "page_scraped", "url": item.get("url"), "streamKind": "info"},
        })
    else:
        msg_text = str(item.get("url") or item.get("message") or item.get("event", "info"))
        await _emit(on_progress, {
            "stage": "running", "type": "info",
            "message": msg_text, "meta": item,
        })


async def _run_remote(
    *,
    message: str,
    args: dict[str, Any],
    on_progress: ProgressCb | None,
    existing_pages: list[dict[str, Any]],
    on_page: PageCb | None = None,
) -> SkillRunResult:
    """
    Call the remote scraper SSE endpoint and stream progress events back.

    Uses two concurrent asyncio tasks to prevent LLM summarization from blocking
    SSE event delivery:
    - Reader task: eagerly reads all SSE lines, emits discovered/info events
      immediately, and enqueues data (page) events for processing.
    - Processor task: drains the queue and calls on_page (LLM + DB) for each page.

    This ensures discovered/scraping events appear in the UI in real-time even
    when LLM summarization takes 10-15s per page.

    When on_page is provided:
    - Page events are routed to on_page one at a time via the queue.
    - The final result has pages stripped (they are in DB via on_page).

    When on_page is None (legacy callers):
    - Old behaviour: pages merged in memory and returned in result.data["pages"].
    """
    started = time.time()
    base = os.getenv("SCRAPER_BASE_URL", "").strip().rstrip("/")
    if not base:
        return SkillRunResult(
            status="error", text="", error="SCRAPER_BASE_URL not configured",
            data=None, duration_ms=0,
        )

    url = str(args.get("url") or "").strip() or _extract_url(message)
    if not url:
        return SkillRunResult(
            status="error", text="scrape-playwright: missing url",
            error="missing_url", data=None,
            duration_ms=int((time.time() - started) * 1000),
        )

    payload: dict[str, Any] = {"url": url}
    for k in ("maxPages", "maxDepth", "deep", "parallel", "maxParallelPages"):
        if k in args and args[k] is not None:
            payload[k] = args[k]

    # Build skip list from already-stored pages so the crawler doesn't re-fetch them.
    existing_urls: set[str] = {
        str(p.get("url") or "").strip().rstrip("/")
        for p in existing_pages
        if isinstance(p, dict) and str(p.get("url") or "").strip()
    }
    if existing_urls:
        await _emit(on_progress, {
            "stage": "running", "type": "info",
            "message": f"reusing {len(existing_urls)} previously scraped urls",
            "meta": {"event": "reuse_existing_urls", "url": url, "reusedCount": len(existing_urls)},
        })

    resume_ck = args.get("resumeCheckpoint") if isinstance(args.get("resumeCheckpoint"), dict) else None
    skip_list = args.get("skipUrls") if isinstance(args.get("skipUrls"), list) else None
    if resume_ck:
        payload["resumeCheckpoint"] = resume_ck
    merged_skip: list[str] = []
    if skip_list:
        merged_skip.extend(str(u).strip() for u in skip_list if str(u).strip())
    merged_skip.extend(sorted(existing_urls))
    deduped_skip = sorted({u.rstrip("/") or u for u in merged_skip if u})
    if deduped_skip:
        payload["skipUrls"] = deduped_skip

    # Sentinel placed in the queue by the reader when SSE stream ends.
    _QUEUE_DONE = object()

    done_result: dict[str, Any] | None = None
    err: str | None = None
    # Track URLs already processed via individual streaming events so we
    # don't double-process them when they also appear in the "done" payload.
    seen_in_stream: set[str] = set()

    # Queue for handing data (page) items from reader → processor.
    page_queue: asyncio.Queue = asyncio.Queue()

    async def _reader(resp: httpx.Response) -> None:
        """
        Eagerly read every SSE line.
        - Info/progress events → emit immediately to on_progress.
        - Data (page) events → emit 'discovered' immediately, then enqueue for
          sequential on_page processing so LLM calls don't block this reader.
        """
        nonlocal done_result

        async for line in resp.aiter_lines():
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if not raw:
                continue
            try:
                meta = json.loads(raw)
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue

            # Recover nested JSON progress from info.message strings
            if str(meta.get("event") or "").strip().lower() == "info" and isinstance(meta.get("message"), str):
                nested, _ = _extract_json_objects_from_text(str(meta.get("message") or ""))
                if nested:
                    for item in nested:
                        item["streamKind"] = _progress_stream_kind(item)
                        await _reader_route(item)
                    continue

            if str(meta.get("event") or "").strip().lower() == "done" and isinstance(meta.get("result"), dict):
                done_result = meta["result"]
                continue

            meta["streamKind"] = _progress_stream_kind(meta)
            await _reader_route(meta)

        # Signal processor that no more pages are coming.
        await page_queue.put(_QUEUE_DONE)

    async def _reader_route(item: dict[str, Any]) -> None:
        """
        Route a single parsed SSE item.
        - Data events (streamKind=="data"): emit 'discovered' immediately, then
          enqueue for on_page processing.
        - Everything else: emit to on_progress immediately (no blocking).
        """
        if on_page is not None and item.get("streamKind") == "data":
            page_url = str(item.get("url") or "").strip().rstrip("/")
            if page_url and page_url not in existing_urls and page_url not in seen_in_stream:
                seen_in_stream.add(page_url)
                # Emit 'discovered' right now — before the LLM even starts.
                await _emit(on_progress, {
                    "stage": "running", "type": "info",
                    "message": page_url,
                    "meta": {"event": "discovered", "url": page_url, "streamKind": "info"},
                })
                # Enqueue for sequential on_page processing (LLM won't block us).
                await page_queue.put(item)
            # Always emit a lightweight tracking event.
            await _emit(on_progress, {
                "stage": "running", "type": "info",
                "message": str(item.get("url") or "page scraped"),
                "meta": {"event": "page_scraped", "url": item.get("url"), "streamKind": "info"},
            })
        else:
            msg_text = str(item.get("url") or item.get("message") or item.get("event", "info"))
            await _emit(on_progress, {
                "stage": "running", "type": "info",
                "message": msg_text, "meta": item,
            })

    async def _processor() -> None:
        """
        Drain the page queue and call on_page for each item.
        Emits 'scraping' just before calling on_page so the UI advances the
        URL from discovered → scraping before LLM work starts.
        """
        while True:
            item = await page_queue.get()
            if item is _QUEUE_DONE:
                break
            page_url = str(item.get("url") or "").strip().rstrip("/")
            # Advance UI: discovered → scraping (Playwright done, about to summarize)
            if page_url:
                await _emit(on_progress, {
                    "stage": "running", "type": "info",
                    "message": page_url,
                    "meta": {"event": "scraping", "url": page_url, "streamKind": "info"},
                })
            await on_page(item)

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{base}/v1/scrape-playwright/stream",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code >= 400:
                err_text = (await resp.aread()).decode("utf-8", errors="replace")
                return SkillRunResult(
                    status="error", text="",
                    error=f"scraper_http_{resp.status_code}: {err_text.strip() or 'request failed'}",
                    data=None,
                    duration_ms=int((time.time() - started) * 1000),
                )

            if on_page is not None:
                # Concurrent: reader eagerly forwards events; processor handles LLM.
                reader_task = asyncio.create_task(_reader(resp))
                await _processor()
                await reader_task
            else:
                # Legacy path (no on_page): read sequentially, collect pages in memory.
                async for line in resp.aiter_lines():
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if not raw:
                        continue
                    try:
                        meta = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(meta, dict):
                        continue

                    if str(meta.get("event") or "").strip().lower() == "info" and isinstance(meta.get("message"), str):
                        nested, _ = _extract_json_objects_from_text(str(meta.get("message") or ""))
                        if nested:
                            for item in nested:
                                item["streamKind"] = _progress_stream_kind(item)
                                await _route_page_or_progress(
                                    item,
                                    on_page=None, on_progress=on_progress,
                                    existing_urls=existing_urls, seen_in_stream=seen_in_stream,
                                )
                            continue

                    if str(meta.get("event") or "").strip().lower() == "done" and isinstance(meta.get("result"), dict):
                        done_result = meta["result"]
                        continue

                    meta["streamKind"] = _progress_stream_kind(meta)
                    await _route_page_or_progress(
                        meta,
                        on_page=None, on_progress=on_progress,
                        existing_urls=existing_urls, seen_in_stream=seen_in_stream,
                    )

    if done_result is None:
        return SkillRunResult(
            status="error", text="",
            error="scraper_stream_ended_without_done",
            data=None,
            duration_ms=int((time.time() - started) * 1000),
        )

    if done_result.get("error"):
        err = str(done_result["error"])

    text = str(done_result.get("text") or "")
    data = done_result.get("data")
    # Backward-compat: some scraper builds return payload directly instead of result.data
    if data is None and isinstance(done_result, dict):
        if {"base_url", "scraped_urls", "failed_urls", "stats", "pages"}.intersection(done_result.keys()):
            data = done_result

    if isinstance(data, dict):
        new_pages = data.get("pages") if isinstance(data.get("pages"), list) else []

        if on_page is not None:
            # Process any pages from "done" not yet handled via individual streaming events
            for page in new_pages:
                if not isinstance(page, dict):
                    continue
                page_url = str(page.get("url") or "").strip().rstrip("/")
                if not page_url or page_url in existing_urls or page_url in seen_in_stream:
                    continue
                seen_in_stream.add(page_url)
                await on_page(page)
            # Strip pages — all are now in DB via on_page
            data = {**data, "pages": [], "reusedPageCount": len(existing_urls)}
        else:
            # Legacy: merge old + new pages in memory (deduped by URL)
            merged: dict[str, dict[str, Any]] = {}
            for p in existing_pages:
                if not isinstance(p, dict):
                    continue
                pu = str(p.get("url") or "").strip().rstrip("/")
                if pu:
                    merged[pu] = p
            for p in new_pages:
                if not isinstance(p, dict):
                    continue
                pu = str(p.get("url") or "").strip().rstrip("/")
                if pu:
                    merged[pu] = p
            if merged:
                data = {**data, "pages": list(merged.values()), "reusedPageCount": len(existing_pages)}

    return SkillRunResult(
        status="error" if err else "ok",
        text=text, error=err, data=data,
        duration_ms=int((time.time() - started) * 1000),
    )


async def run_playwright_skill(
    message: str,
    args: dict[str, Any],
    on_progress: ProgressCb | None,
    on_page: PageCb | None = None,
) -> SkillRunResult:
    """
    Entry point for the scrape-playwright skill.

    1. For single-page scrapes, check scraped_pages table for a cached result.
    2. Otherwise call the remote scraper, merging previously stored pages.
    3. Returns the raw result with pages in result.data["pages"].
       The caller (service.py) is responsible for summarising and persisting
       pages to the scraped_pages table.
    """
    url = str(args.get("url") or "").strip() or _extract_url(message)

    # ── 1. Cache hit for homepage-only scrapes ──────────────────────────────
    if url and _is_homepage_scrape(args):
        existing, existing_ids = await _load_existing_pages(url)
        if existing:
            await _emit(on_progress, {
                "stage": "running", "type": "info",
                "message": f"cache hit for {url}",
                "meta": {"event": "cache_hit", "url": url, "cachedPageCount": len(existing)},
            })
            if on_page is not None:
                # Caller wants per-page delivery even on cache hits
                for page in existing:
                    if isinstance(page, dict):
                        await on_page(page)
                cached_data: dict[str, Any] = {
                    "base_url": url, "pages": [], "reusedPageCount": len(existing),
                }
            else:
                cached_data = {
                    "base_url": url, "pages": existing, "reusedPageCount": len(existing),
                }
            return SkillRunResult(status="ok", text="", error=None, data=cached_data, duration_ms=0)

    # ── 2. Load previously scraped pages for skip-list / merge ─────────────
    existing_pages, existing_page_ids = await _load_existing_pages(url) if url else ([], [])

    # ── 3. Call remote scraper ───────────────────────────────────────────────
    return await _run_remote(
        message=message, args=args,
        on_progress=on_progress,
        existing_pages=existing_pages,
        on_page=on_page,
    ), existing_page_ids


