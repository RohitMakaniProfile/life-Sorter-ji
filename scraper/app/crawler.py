"""Crawl orchestration — parallel async crawl, resume, and sequential fallback."""

import asyncio
import hashlib
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from threading import Thread

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None  # type: ignore[assignment]
    PWTimeout = Exception  # type: ignore[assignment,misc]

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeoutAsync
except ImportError:
    async_playwright = None  # type: ignore[assignment]
    PWTimeoutAsync = Exception  # type: ignore[assignment,misc]

from html_extractor import extract_content_elements_from_page, extract_text_from_html
from page_scraper import _scrape_single_page_async
from progress import _progress
from url_priority import _get_url_priority
from url_utils import (
    _fetch_sitemap_urls,
    _is_blog_url,
    norm_crawl_url,
    parse_links,
    parse_schema_types,
    should_skip_url,
)


def _create_robots_parser(base_url: str) -> urllib.robotparser.RobotFileParser | None:
    """Fetch and parse robots.txt. Returns None if unreachable or no Disallow rules."""
    try:
        robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
        req = urllib.request.Request(
            robots_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PlaywrightCrawler/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8", errors="replace")
        if "disallow" not in content.lower():
            _progress({"event": "robots_info", "message": "robots.txt has no Disallow rules, allowing all URLs"})
            return None
        robots_parser = urllib.robotparser.RobotFileParser()
        robots_parser.parse(content.splitlines())
        return robots_parser
    except Exception as e:
        _progress({"event": "robots_info", "message": f"Could not fetch robots.txt: {e}, allowing all URLs"})
        return None


def _hydrate_parallel_resume(
    resume: dict | None,
    skip_urls: set[str],
    base_url: str,
) -> tuple[deque, set, set, list[str], list[dict]] | None:
    """Restore crawl state from a v1 parallel checkpoint, or return None for a fresh crawl."""
    if not resume or not isinstance(resume, dict):
        return None
    if int(resume.get("v") or 0) != 1 or not resume.get("parallel"):
        return None
    to_visit = deque(norm_crawl_url(u) for u in (resume.get("to_visit") or []) if norm_crawl_url(u))
    discovered = {norm_crawl_url(u) for u in (resume.get("discovered") or []) if norm_crawl_url(u)}
    scraped = {norm_crawl_url(u) for u in (resume.get("scraped") or []) if norm_crawl_url(u)}
    scraped_urls = [norm_crawl_url(u) for u in (resume.get("scraped_urls") or []) if norm_crawl_url(u)]
    failed_list = [x for x in (resume.get("failed_urls") or []) if isinstance(x, dict)]
    skip_norm = {norm_crawl_url(u) for u in skip_urls if norm_crawl_url(u)}
    for u in skip_norm:
        scraped.add(u)
        if u not in scraped_urls:
            scraped_urls.append(u)
    bu = norm_crawl_url(base_url)
    if bu and bu not in discovered:
        discovered.add(bu)
    return to_visit, discovered, scraped, scraped_urls, failed_list


async def _crawl_parallel_async(
    base_url: str,
    base_domain: str,
    max_pages: int,
    max_depth: int,
    respect_robots: bool,
    robots_parser,
    t_start: float,
    headless: bool,
    *,
    resume: dict | None = None,
    skip_urls: set[str] | None = None,
    max_parallel_pages: int = 1,
) -> dict:
    skip_norm = {norm_crawl_url(u) for u in (skip_urls or set()) if norm_crawl_url(u)}
    hydrated = _hydrate_parallel_resume(resume, skip_norm, base_url)

    if hydrated is not None:
        to_visit, discovered, scraped, scraped_urls, failed_list = hydrated
        for u in skip_norm:
            scraped.add(u)
            if u not in scraped_urls:
                scraped_urls.append(u)
    else:
        to_visit: deque = deque()
        discovered: set = set()
        scraped: set = set()
        scraped_urls: list[str] = []
        failed_list: list[dict] = []
        bu = norm_crawl_url(base_url)
        if bu:
            to_visit.append(bu)
            discovered.add(bu)
        sitemap_urls = _fetch_sitemap_urls(base_url, base_domain)[:500]
        for u in sitemap_urls:
            un = norm_crawl_url(u)
            if not un:
                continue
            if un not in discovered and not should_skip_url(un) and not _is_blog_url(un):
                if not respect_robots or not robots_parser or robots_parser.can_fetch("*", un):
                    to_visit.append(un)
                    discovered.add(un)
        _progress({"event": "sitemap_loaded", "urls_found": len(sitemap_urls), "added_to_discovered": len(discovered)})

    collect_pages = max_pages <= 5
    pages_data: list[dict] = []
    lock = asyncio.Lock()
    stop_flag = asyncio.Event()
    discovery_idle_count = 0
    all_scrapers_idle_rounds = 0
    IDLE_THRESHOLD = 2
    ALL_IDLE_ROUNDS_THRESHOLD = 5
    scraper_idle_flags: dict[int, bool] = {}

    async def _emit_checkpoint() -> None:
        async with lock:
            payload = {
                "v": 1,
                "parallel": True,
                "base_url": norm_crawl_url(base_url),
                "to_visit": list(to_visit),
                "discovered": list(discovered),
                "scraped": list(scraped),
                "scraped_urls": list(scraped_urls),
                "failed_urls": list(failed_list),
            }
        _progress({"event": "checkpoint", "parallel": True, "payload": payload, "streamKind": "info"})

    _progress({"event": "started", "parallel": True})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_scrape = await browser.new_context(viewport={"width": 1280, "height": 900})

        async def discovery_coro():
            nonlocal discovery_idle_count
            while not stop_flag.is_set():
                urls_transferred = 0
                async with lock:
                    if len(discovered) >= max_pages * 2:
                        return
                    while to_visit and urls_transferred < 10:
                        url = to_visit.popleft()
                        if url and url not in discovered:
                            discovered.add(url)
                            urls_transferred += 1
                            _progress({"event": "discovered", "url": url})
                if urls_transferred == 0:
                    discovery_idle_count += 1
                    async with lock:
                        all_scrapers_idle = all(scraper_idle_flags.get(i, False) for i in range(max_parallel_pages))
                        current_discovered = len(discovered)
                        current_scraped = len(scraped_urls)
                        current_to_visit = len(to_visit)
                    if discovery_idle_count >= IDLE_THRESHOLD and all_scrapers_idle:
                        _progress({
                            "event": "idle_check",
                            "discovery_idle_count": discovery_idle_count,
                            "all_scrapers_idle": all_scrapers_idle,
                            "discovered": current_discovered,
                            "scraped": current_scraped,
                            "to_visit": current_to_visit,
                            "threshold": ALL_IDLE_ROUNDS_THRESHOLD,
                        })
                        if discovery_idle_count >= ALL_IDLE_ROUNDS_THRESHOLD:
                            _progress({"event": "stopping", "reason": "all_idle_threshold_reached"})
                            stop_flag.set()
                            return
                    await asyncio.sleep(0.3)
                else:
                    discovery_idle_count = 0
                    await asyncio.sleep(0.1)

        async def scraper_coro(scraper_index: int):
            nonlocal scraped_urls, failed_list, all_scrapers_idle_rounds
            consecutive_idle = 0
            while not stop_flag.is_set():
                async with lock:
                    if len(scraped_urls) >= max_pages:
                        stop_flag.set()
                        return
                    to_scrape = [u for u in discovered if u not in scraped and not _is_blog_url(u)]
                    if not to_scrape:
                        url = None
                    else:
                        url = sorted(to_scrape, key=_get_url_priority, reverse=True)[0]
                        scraped.add(url)
                        _progress({
                            "event": "url_selected",
                            "url": url,
                            "priority": _get_url_priority(url),
                            "scraper_index": scraper_index,
                        })
                if url is None:
                    consecutive_idle += 1
                    async with lock:
                        scraper_idle_flags[scraper_index] = True
                        all_idle = all(scraper_idle_flags.get(i, False) for i in range(max_parallel_pages))
                        current_scraped_count = len(scraped_urls)
                    if all_idle and discovery_idle_count >= IDLE_THRESHOLD and current_scraped_count > 0:
                        all_scrapers_idle_rounds += 1
                        _progress({
                            "event": "scraper_idle_check",
                            "scraper_index": scraper_index,
                            "consecutive_idle": consecutive_idle,
                            "all_scrapers_idle_rounds": all_scrapers_idle_rounds,
                            "scraped_count": current_scraped_count,
                        })
                        if all_scrapers_idle_rounds >= ALL_IDLE_ROUNDS_THRESHOLD:
                            stop_flag.set()
                            return
                    await asyncio.sleep(0.5)
                    continue
                consecutive_idle = 0
                async with lock:
                    scraper_idle_flags[scraper_index] = False
                    all_scrapers_idle_rounds = 0
                if url in skip_norm:
                    async with lock:
                        if url not in scraped_urls:
                            scraped_urls.append(url)
                    await _emit_checkpoint()
                    await asyncio.sleep(0.2)
                    continue
                rec = await _scrape_single_page_async(context_scrape, url, 0, base_domain, robots_parser, respect_robots)
                if rec:
                    async with lock:
                        scraped_urls.append(url)
                        if collect_pages:
                            pages_data.append(rec)
                    _progress({"event": "page_data", **rec})
                    await _emit_checkpoint()
                    internal_links = rec.get("links_internal", [])
                    _progress({
                        "event": "links_found",
                        "url": url,
                        "internal_links_count": len(internal_links),
                        "sample_links": internal_links[:5] if internal_links else [],
                    })
                    links_added = 0
                    for link in internal_links:
                        ln = norm_crawl_url(link)
                        if not ln or _is_blog_url(ln):
                            continue
                        async with lock:
                            if ln in discovered or should_skip_url(ln):
                                continue
                            if respect_robots and robots_parser and not robots_parser.can_fetch("*", ln):
                                continue
                            to_visit.append(ln)
                            discovered.add(ln)
                            links_added += 1
                    _progress({
                        "event": "scraper_links_summary",
                        "url": url,
                        "links_added": links_added,
                        "total_discovered": len(discovered),
                        "total_scraped": len(scraped_urls),
                    })
                else:
                    async with lock:
                        failed_list.append({"url": url, "error": "scrape_failed"})
                await asyncio.sleep(0.2)

        scraper_coros = [scraper_coro(i) for i in range(max(1, max_parallel_pages))]
        await asyncio.wait_for(asyncio.gather(discovery_coro(), *scraper_coros), timeout=3600)
        await context_scrape.close()
        await browser.close()

    return {
        "base_url": base_url,
        "scraped_urls": scraped_urls,
        "failed_urls": failed_list,
        "pages": pages_data if collect_pages else [],
        "stats": {
            "total_pages": len(scraped_urls),
            "failed_pages": len(failed_list),
            "skipped_pages": 0,
            "crawl_duration_s": int(time.time() - t_start),
        },
    }


def crawl_with_playwright(
    base_url: str,
    max_pages: int,
    max_depth: int,
    respect_robots: bool,
    headless: bool,
    deep: bool = False,
    parallel: bool = False,
    resume_checkpoint: dict | None = None,
    skip_urls: list[str] | None = None,
    max_parallel_pages: int = 1,
) -> dict:
    t_start = time.time()

    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    robots_parser = _create_robots_parser(base_url) if respect_robots else None
    skip_set = {norm_crawl_url(u) for u in (skip_urls or []) if norm_crawl_url(u)}

    if parallel:
        if async_playwright is None:
            raise RuntimeError("playwright async_api required for parallel crawl")
        coro = _crawl_parallel_async(
            base_url, base_domain, max_pages, max_depth,
            respect_robots, robots_parser, t_start, headless,
            resume=resume_checkpoint,
            skip_urls=skip_set,
            max_parallel_pages=max_parallel_pages,
        )
        try:
            return asyncio.run(coro)
        except RuntimeError:
            result_box: dict[str, dict] = {}
            err_box: dict[str, BaseException] = {}

            def _runner() -> None:
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result_box["value"] = loop.run_until_complete(coro)
                except BaseException as e:
                    err_box["err"] = e
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass

            t = Thread(target=_runner, daemon=True)
            t.start()
            t.join()
            if "err" in err_box:
                raise err_box["err"]
            return result_box.get("value") or {}

    # Sequential BFS fallback
    scraped_urls: list[str] = []
    failed_list: list[dict] = []
    collect_pages = max_pages <= 5
    pages_data: list[dict] = []
    visited: set[str] = set()
    queue: deque = deque([(base_url, 0)])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        while queue and len(scraped_urls) < max_pages:
            url, depth = queue.popleft()
            url_norm = url.rstrip("/") or url

            if url_norm in visited:
                continue
            visited.add(url_norm)

            if should_skip_url(url_norm) or _is_blog_url(url_norm) or depth > max_depth:
                continue
            if respect_robots and robots_parser and not robots_parser.can_fetch("*", url_norm):
                continue

            _progress({"event": "discovered", "url": url_norm, "index": len(visited)})

            page = context.new_page()
            try:
                try:
                    page.goto(url_norm, wait_until="networkidle", timeout=12000)
                except PWTimeout:
                    try:
                        page.goto(url_norm, wait_until="load", timeout=10000)
                    except PWTimeout:
                        pass
                time.sleep(1.0)
                html = page.content()
                body_text = extract_text_from_html(html)
                rec = {
                    "url": url_norm,
                    "depth": depth,
                    "status_code": 0,
                    "title": page.title() or "",
                    "meta_description": "",
                    "meta_keywords": "",
                    "elements": extract_content_elements_from_page(page, html),
                    "links_internal": [],
                    "schema_types": parse_schema_types(html),
                    "canonical": "",
                    "robots": "",
                    "content_hash": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "js_rendered": True,
                    "network_requests": [],
                    "local_storage_keys": [],
                    "cookie_names": [],
                    "links_external": [],
                }
                _progress({"event": "page_data", **rec})
                scraped_urls.append(url_norm)
                if collect_pages:
                    pages_data.append(rec)

                internal, _ = parse_links(html, url_norm, base_domain)
                if depth < max_depth:
                    for link in internal:
                        ln = link.rstrip("/") or link
                        if ln not in visited and not _is_blog_url(ln):
                            queue.append((ln, depth + 1))
            except Exception as e:
                failed_list.append({"url": url_norm, "error": str(e)})
            finally:
                page.close()
                time.sleep(0.2)

        context.close()
        browser.close()

    return {
        "base_url": base_url,
        "scraped_urls": scraped_urls,
        "failed_urls": failed_list,
        "pages": pages_data if collect_pages else [],
        "stats": {
            "total_pages": len(scraped_urls),
            "failed_pages": len(failed_list),
            "skipped_pages": 0,
            "crawl_duration_s": int(time.time() - t_start),
        },
    }