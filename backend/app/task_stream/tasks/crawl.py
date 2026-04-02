from __future__ import annotations

from typing import Any

from app.task_stream.registry import register_task_stream
from app.utils.url_sanitize import sanitize_http_url
from app.services.crawl_persistence import persist_successful_crawl
from app.services.crawl_service import crawl_website, detect_url_type


def _quick_summary(crawl_raw: dict[str, Any], website_url: str) -> dict[str, Any]:
    homepage = crawl_raw.get("homepage") or {}
    title = str(homepage.get("title") or "")
    meta_desc = str(homepage.get("meta_desc") or "")
    tech = crawl_raw.get("tech_signals") or []
    ctas = crawl_raw.get("cta_patterns") or []
    pages = crawl_raw.get("pages_crawled") or []

    points: list[str] = []
    if title:
        points.append(f"Homepage title: {title}")
    if meta_desc:
        points.append(f"Meta description: {meta_desc[:160]}")
    if tech:
        points.append(f"Tech signals: {', '.join(tech[:8])}")
    if ctas:
        points.append(f"CTA patterns: {', '.join(ctas[:8])}")
    if pages:
        points.append(f"Pages crawled: {len(pages)}")
    if not points:
        points.append(f"Crawled: {website_url}")

    return {
        "crawl_status": "complete",
        "points": points[:8],
        "website_url": website_url,
    }


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

    crawl_raw = await crawl_website(website_url, progress_cb=_progress)
    await send("stage", stage="summarizing", label="Building summary")

    crawl_summary = _quick_summary(crawl_raw, website_url)

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

