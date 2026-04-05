from __future__ import annotations

from typing import Any

import structlog

from app.task_stream.registry import register_task_stream
from app.utils.url_sanitize import sanitize_http_url
from app.services.crawl_persistence import persist_successful_crawl
from app.services.crawl_service import (
    crawl_website,
    crawl_website_playwright,
    crawl_gbp,
    crawl_social_profile,
    generate_gbp_summary,
    generate_crawl_summary,
    detect_url_type,
)

logger = structlog.get_logger()


@register_task_stream("crawl")
async def crawl_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Efficient background crawl task (task-stream).

    Input payload:
      - session_id (injected by task-stream service)
      - website_url: str (required)

    Emits:
      - stage events with crawl phases
      - done with { crawl_raw, crawl_summary }
    """
    raw_url = str(payload.get("website_url") or payload.get("url") or "").strip()
    if not raw_url:
        raise ValueError("website_url is required")

    website_url = sanitize_http_url(raw_url) or raw_url
    await send("stage", stage="starting", label="Starting crawl", url=website_url)

    url_type = detect_url_type(website_url)
    await send("stage", stage="detecting", label=f"Detected url type: {url_type}", url_type=url_type)

    async def _progress(**p: Any) -> None:
        await send("stage", stage=p.get("phase") or "running", label="Crawling", **p)

    if url_type == "gbp":
        crawl_raw = await crawl_gbp(website_url)
    elif url_type == "social_profile":
        crawl_raw = await crawl_social_profile(website_url)
    else:
        try:
            crawl_raw = await crawl_website_playwright(website_url, progress_cb=_progress)
        except Exception as pw_err:
            logger.warning(
                "Playwright crawl failed, falling back to httpx",
                url=website_url,
                error=str(pw_err),
            )
            crawl_raw = await crawl_website(website_url, progress_cb=_progress)

    await send("stage", stage="summarizing", label="Building summary")

    if url_type == "gbp":
        crawl_summary = await generate_gbp_summary(crawl_raw, website_url)
    else:
        crawl_summary = await generate_crawl_summary(crawl_raw, website_url)

    sid = str(payload.get("session_id") or "").strip()
    uid = str(payload.get("user_id") or "").strip() or None
    if sid:
        await persist_successful_crawl(
            session_id=sid,
            user_id=uid,
            input_url=website_url,
            url_type=url_type,
            crawl_raw=crawl_raw,
            crawl_summary=crawl_summary,
        )

    return {"crawl_raw": crawl_raw, "crawl_summary": crawl_summary}
