#!/usr/bin/env python3
"""
Vendored from `backend/skills/scrape-playwright/scripts/playwright_scraper.py`.

This script prints one JSON object per line to stderr (progress), and prints one
final JSON object to stdout (result).
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from threading import Lock, Thread
_PROGRESS_LOCK = Lock()


try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeoutAsync
except ImportError:
    async_playwright = None
    PWTimeoutAsync = Exception

# Optional OCR support via Google Vision API
try:
    from ocr_helper import ocr_page_sync, ocr_page_async, merge_ocr_into_elements
except ImportError:
    def ocr_page_sync(page, api_key=None): return ""  # noqa: E731
    async def ocr_page_async(page, api_key=None): return ""  # noqa: E731
    def merge_ocr_into_elements(elements, ocr_text): return elements  # noqa: E731

_OCR_API_KEY = os.getenv("GOOGLE_VISION_API_KEY", "").strip() or None


SKIP_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".mp3",
    ".zip",
    ".tar",
    ".gz",
    ".exe",
    ".dmg",
    ".css",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
    ".xml",
    ".json",  # sitemaps, API responses — we only scrape HTML pages
}


def norm_crawl_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    return u.rstrip("/") or u


def should_skip_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""
    return ext in SKIP_EXTENSIONS


def extract_text_from_html(html: str) -> str:
    """Simple regex text extraction."""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()[:50000]


def extract_content_elements(html: str, max_items: int = 500) -> list[dict]:
    """Fallback parser: preserve approximate DOM order as typed elements."""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    token_re = re.compile(
        r"(?is)"
        r"(<h[1-3][^>]*>.*?</h[1-3]>)|"
        r"(<p[^>]*>.*?</p>)|"
        r"(<li[^>]*>.*?</li>)|"
        r"(<img[^>]*alt=[\"'][^\"']+[\"'][^>]*>)"
    )
    out: list[dict] = []
    for m in token_re.finditer(html):
        token = m.group(0)
        if not token:
            continue
        low = token.lower()
        if low.startswith("<img"):
            am = re.search(r'(?is)alt=["\']([^"\']+)["\']', token)
            val = re.sub(r"\s+", " ", (am.group(1) if am else "")).strip()
            if val:
                out.append({"type": "img_alt", "content": val})
        else:
            text = re.sub(r"<[^>]+>", " ", token)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                tag = "text"
                if low.startswith("<h1"):
                    tag = "h1"
                elif low.startswith("<h2"):
                    tag = "h2"
                elif low.startswith("<h3"):
                    tag = "h3"
                elif low.startswith("<p"):
                    tag = "p"
                elif low.startswith("<li"):
                    tag = "li"
                out.append({"type": tag, "content": text})
        if len(out) >= max_items:
            break
    return out


_ELEMENTS_EVAL_JS = """
(maxItems) => {
  const out = [];
  const nodes = document.querySelectorAll('h1,h2,h3,p,li,img[alt]');
  for (const node of nodes) {
    if (out.length >= (maxItems || 500)) break;
    const tag = (node.tagName || '').toLowerCase();
    let type = tag;
    let content = '';
    if (tag === 'img') {
      type = 'img_alt';
      content = (node.getAttribute('alt') || '').trim();
    } else {
      content = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
    }
    if (!content) continue;
    out.push({ type, content });
  }
  return out;
}
"""


def extract_content_elements_from_page(page, html: str, max_items: int = 500) -> list[dict]:
    """Primary extractor: ordered DOM traversal via Playwright evaluate."""
    try:
        data = page.evaluate(_ELEMENTS_EVAL_JS, max_items)
        if isinstance(data, list):
            cleaned: list[dict] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                t = str(item.get("type") or "").strip().lower()
                c = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
                if not t or not c:
                    continue
                cleaned.append({"type": t, "content": c})
                if len(cleaned) >= max_items:
                    break
            if cleaned:
                return cleaned
    except Exception:
        pass
    return extract_content_elements(html, max_items=max_items)


def parse_links(html: str, page_url: str, base_domain: str) -> tuple[list, list]:
    internal, external = [], []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\'#][^"\']*)["\']', html, re.I):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urllib.parse.urljoin(page_url, href).split("#")[0].split("?")[0]
        lp = urllib.parse.urlparse(full)
        if lp.scheme not in ("http", "https"):
            continue
        netloc_lower = lp.netloc.lower()
        # Only accept exact domain match - completely skip subdomains
        if netloc_lower == base_domain.lower():
            if full not in internal:
                internal.append(full)
        else:
            if full not in external:
                external.append(full)
    return internal, external


def parse_schema_types(html: str) -> list[str]:
    types = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S
    ):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                t = obj.get("@type")
                if isinstance(t, str):
                    types.append(t)
                elif isinstance(t, list):
                    types.extend(t)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        t = item.get("@type")
                        if isinstance(t, str):
                            types.append(t)
        except Exception:
            pass
    return types


def _progress(obj: dict) -> None:
    if "streamKind" not in obj:
        evt = str(obj.get("event") or "").strip().lower()
        obj["streamKind"] = "data" if evt == "page_data" else "info"
    # Parallel workers can emit concurrently; serialize stderr writes so each line
    # remains a valid standalone JSON object.
    with _PROGRESS_LOCK:
        print(json.dumps(obj), file=sys.stderr, flush=True)


def _fetch_sitemap_urls(base_url: str, base_domain: str) -> list[str]:
    urls = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PlaywrightCrawler/1.0)",
        "Accept": "application/xml,text/xml,text/plain,*/*",
    }
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap.txt"):
        sitemap_url = urllib.parse.urljoin(base_url, path)
        try:
            req = urllib.request.Request(sitemap_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                content = r.read().decode("utf-8", errors="replace")
        except Exception:
            continue
        if not content.strip():
            continue
        found = re.findall(r"<loc>\s*([^<]+)\s*</loc>", content, re.I | re.S)
        if not found and path.endswith(".txt"):
            found = [ln.strip() for ln in content.splitlines() if ln.strip().startswith("http")]
        for u in found:
            u = u.strip()
            if not u:
                continue
            parsed = urllib.parse.urlparse(u)
            if parsed.scheme not in ("http", "https"):
                continue
            netloc = parsed.netloc.lower()
            # Only accept exact domain match - completely skip subdomains
            if netloc == base_domain.lower():
                if not should_skip_url(u):
                    urls.append(u)
        if urls:
            break
    return list(dict.fromkeys(urls))


def _is_blog_url(url: str) -> bool:
    return "blog" in url.lower()


# URL priority scoring - higher score = more important
# These URLs contain key business information
HIGH_PRIORITY_KEYWORDS = [
    "about",
    "pricing", "price", "plans",
    "contact", "contact-us",
    "careers", "jobs", "hiring",
    "team", "company",
    "features", "product",
    "services",
    "faq", "help",
    "enterprise",
    "demo",
    "signup", "sign-up", "register",
    "privacy", "terms",
]

# These URLs are typically less important for business understanding
LOW_PRIORITY_KEYWORDS = [
    "docs", "documentation", "api-reference",
    "tutorial", "tutorials", "guide", "guides",
    "blog", "news", "updates",
    "changelog", "release-notes",
    "community", "forum", "support",
    "legal", "compliance",
]

# Subdomains to completely skip (not just deprioritize)
SKIP_SUBDOMAINS = [
    "docs.",
    "app.",
    "api.",
    "status.",
    "community.",
    "forum.",
    "help.",
    "blog.",
    "support.",
    "cdn.",
    "static.",
    "assets.",
    "media.",
]


def _is_subdomain_url(url: str, base_domain: str) -> bool:
    """Check if URL is from a subdomain that should be skipped."""
    parsed = urllib.parse.urlparse(url.lower())
    netloc = parsed.netloc
    
    # If netloc equals base_domain exactly, it's not a subdomain
    if netloc == base_domain.lower():
        return False
    
    # Check if it's a subdomain of base_domain
    if netloc.endswith("." + base_domain.lower()):
        # It's a subdomain - check if it's in the skip list
        subdomain_prefix = netloc[: -(len(base_domain) + 1)]  # Get the subdomain part
        for skip_sub in SKIP_SUBDOMAINS:
            skip_prefix = skip_sub.rstrip(".")
            if subdomain_prefix == skip_prefix or subdomain_prefix.endswith("." + skip_prefix):
                return True
    
    return False


def _get_url_priority(url: str) -> int:
    """
    Calculate priority score for a URL.
    Higher score = higher priority (will be scraped first).

    Score ranges:
    - 100+: Homepage
    - 50-99: High priority business pages
    - 10-49: Normal pages
    - 0-9: Low priority (docs, tutorials, etc.)
    """
    url_lower = url.lower()
    parsed = urllib.parse.urlparse(url_lower)
    path = parsed.path.strip("/")

    # Homepage gets highest priority
    if not path or path == "":
        return 100


    # Check for high priority keywords in path
    for keyword in HIGH_PRIORITY_KEYWORDS:
        if keyword in path:
            # Shorter paths with high priority keywords are even better
            # e.g., /pricing is better than /docs/pricing/guide
            depth = path.count("/")
            return max(50, 80 - depth * 10)

    # Check for low priority keywords
    for keyword in LOW_PRIORITY_KEYWORDS:
        if keyword in path:
            return 5

    # Default priority based on path depth
    # Shallower paths are usually more important
    depth = path.count("/")
    return max(10, 40 - depth * 5)




async def _scrape_single_page_async(context, url_norm: str, depth: int, base_domain: str, robots_parser, respect_robots: bool):
    network_requests = []

    def on_request(req):
        if req.resource_type in ("xhr", "fetch"):
            network_requests.append(req.url)

    page = await context.new_page()
    page.on("request", on_request)
    try:
        try:
            resp = await page.goto(url_norm, wait_until="networkidle", timeout=30000)
        except PWTimeoutAsync:
            resp = None
        status_code = resp.status if resp else 0
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PWTimeoutAsync:
            pass
        html = await page.content()
        body_text = extract_text_from_html(html)

        # ── Extract image URLs ─────────────────────────────────────────────────
        image_urls: list[str] = []
        try:
            image_urls = await page.eval_on_selector_all(
                "img[src]",
                "els => els.map(e => e.src).filter(s => s && s.startsWith('http'))",
            )
        except Exception:
            image_urls = []

        elements: list[dict] = []
        try:
            data = await page.evaluate(_ELEMENTS_EVAL_JS, 500)
            if isinstance(data, list):
                elements = [
                    {
                        "type": str(it.get("type") or "").strip().lower(),
                        "content": re.sub(r"\s+", " ", str(it.get("content") or "")).strip(),
                    }
                    for it in data
                    if isinstance(it, dict) and str(it.get("type") or "").strip() and str(it.get("content") or "").strip()
                ][:500]
        except Exception:
            elements = []
        if not elements:
            elements = extract_content_elements(html)

        # OCR: screenshot the page and extract text via Google Vision API
        ocr_text = await ocr_page_async(page, _OCR_API_KEY) if _OCR_API_KEY else ""
        if ocr_text:
            elements = merge_ocr_into_elements(elements, ocr_text)

        internal_links, _ = parse_links(html, url_norm, base_domain)
        content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()

        rec = {
            "url": url_norm,
            "depth": depth,
            "status_code": status_code,
            "title": (await page.title()) if hasattr(page, "title") else "",
            "meta_description": "",
            "meta_keywords": "",
            "elements": elements,
            "body_text": body_text,
            "ocr_text": ocr_text,
            "links_internal": internal_links,
            "schema_types": parse_schema_types(html),
            "canonical": "",
            "robots": "",
            "content_hash": content_hash,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "js_rendered": True,
            "network_requests": list(dict.fromkeys(network_requests))[:30],
            "local_storage_keys": [],
            "cookie_names": [],
            "links_external": [],
            "image_urls": image_urls,
        }
        return rec
    except Exception:
        return None
    finally:
        await page.close()
        await asyncio.sleep(0.3)


def _hydrate_parallel_resume(
    resume: dict | None,
    skip_urls: set[str],
    base_url: str,
) -> tuple[deque, set, set, list[str], list[dict]] | None:
    """
    Return bootstrapped state from v1 parallel checkpoint, or None for fresh crawl.
    """
    if not resume or not isinstance(resume, dict):
        return None
    if int(resume.get("v") or 0) != 1 or not resume.get("parallel"):
        return None
    to_visit = deque(norm_crawl_url(u) for u in (resume.get("to_visit") or []) if norm_crawl_url(u))
    discovered = {norm_crawl_url(u) for u in (resume.get("discovered") or []) if norm_crawl_url(u)}
    scraped = {norm_crawl_url(u) for u in (resume.get("scraped") or []) if norm_crawl_url(u)}
    scraped_urls = [norm_crawl_url(u) for u in (resume.get("scraped_urls") or []) if norm_crawl_url(u)]
    failed_list = list(resume.get("failed_urls") or [])
    if not isinstance(failed_list, list):
        failed_list = []
    failed_list = [x for x in failed_list if isinstance(x, dict)]
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

    to_visit: deque
    discovered: set
    scraped: set
    scraped_urls: list[str]
    failed_list: list[dict]

    if hydrated is not None:
        to_visit, discovered, scraped, scraped_urls, failed_list = hydrated
        for u in skip_norm:
            scraped.add(u)
            if u not in scraped_urls:
                scraped_urls.append(u)
    else:
        to_visit = deque()
        discovered = set()
        scraped = set()
        scraped_urls = []
        failed_list = []
        bu = norm_crawl_url(base_url)
        if bu:
            to_visit.append(bu)
            discovered.add(bu)  # Add base URL to discovered so scrapers can start immediately
        # Fetch sitemap URLs and add them DIRECTLY to discovered (not just to_visit)
        # This allows scrapers to start working immediately without waiting for discovery
        sitemap_urls = _fetch_sitemap_urls(base_url, base_domain)[:500]
        for u in sitemap_urls:
            un = norm_crawl_url(u)
            if not un:
                continue
            if un not in discovered and not should_skip_url(un) and not _is_blog_url(un):
                if not respect_robots or not robots_parser or robots_parser.can_fetch("*", un):
                    to_visit.append(un)
                    discovered.add(un)  # Add to discovered so scrapers can use it immediately
        _progress({"event": "sitemap_loaded", "urls_found": len(sitemap_urls), "added_to_discovered": len(discovered)})

    # Collect page data for the "pages" array in the final result
    # Only collect for small crawls (<=5 pages) to avoid memory issues
    collect_pages = max_pages <= 5
    pages_data: list[dict] = []

    lock = asyncio.Lock()
    stop_flag = asyncio.Event()
    discovery_idle_count = 0
    # Track consecutive "all scrapers idle" rounds, not per-scraper increments
    all_scrapers_idle_rounds = 0
    IDLE_THRESHOLD = 2
    # How many consecutive rounds where ALL scrapers are idle before stopping
    ALL_IDLE_ROUNDS_THRESHOLD = 5
    # Track which scrapers are currently idle (by index)
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
        # Only need scrape context - discovery no longer loads pages
        context_scrape = await browser.new_context(viewport={"width": 1280, "height": 900})

        async def discovery_coro():
            """
            Fast discovery: just moves URLs from to_visit to discovered.
            Scrapers are responsible for loading pages and finding new links.
            This avoids the slow Playwright page load in the discovery loop.
            """
            nonlocal discovery_idle_count
            while not stop_flag.is_set():
                urls_transferred = 0
                async with lock:
                    if len(discovered) >= max_pages * 2:
                        return
                    # Transfer multiple URLs at once for efficiency
                    while to_visit and urls_transferred < 10:
                        url = to_visit.popleft()
                        if url and url not in discovered:
                            discovered.add(url)
                            urls_transferred += 1
                            _progress({"event": "discovered", "url": url})

                if urls_transferred == 0:
                    discovery_idle_count += 1
                    # Check if all scrapers are idle AND discovery is idle
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
                            "threshold": ALL_IDLE_ROUNDS_THRESHOLD
                        })
                        # Give more time - wait for ALL_IDLE_ROUNDS_THRESHOLD consecutive checks
                        if discovery_idle_count >= ALL_IDLE_ROUNDS_THRESHOLD:
                            _progress({"event": "stopping", "reason": "all_idle_threshold_reached"})
                            stop_flag.set()
                            return
                    await asyncio.sleep(0.3)
                else:
                    discovery_idle_count = 0
                    await asyncio.sleep(0.1)  # Small delay to allow scrapers to pick up work


        async def scraper_coro(scraper_index: int):
            nonlocal scraped_urls, failed_list, all_scrapers_idle_rounds
            consecutive_idle = 0
            while not stop_flag.is_set():
                async with lock:
                    if len(scraped_urls) >= max_pages:
                        stop_flag.set()
                        return
                    # Get URLs that haven't been scraped yet
                    to_scrape = [u for u in discovered if u not in scraped and not _is_blog_url(u)]
                    if not to_scrape:
                        url = None
                    else:
                        # Sort by priority (highest first) and pick the best one
                        to_scrape_sorted = sorted(to_scrape, key=_get_url_priority, reverse=True)
                        url = to_scrape_sorted[0]
                        scraped.add(url)
                        _progress({
                            "event": "url_selected",
                            "url": url,
                            "priority": _get_url_priority(url),
                            "scraper_index": scraper_index
                        })
                if url is None:
                    consecutive_idle += 1
                    async with lock:
                        scraper_idle_flags[scraper_index] = True
                        # Check if ALL scrapers are idle
                        all_idle = all(scraper_idle_flags.get(i, False) for i in range(max_parallel_pages))
                        current_scraped_count = len(scraped_urls)

                    # Only consider stopping if we have scraped at least 1 page
                    # This prevents premature exit while the first page is still loading
                    if all_idle and discovery_idle_count >= IDLE_THRESHOLD and current_scraped_count > 0:
                        all_scrapers_idle_rounds += 1
                        _progress({
                            "event": "scraper_idle_check",
                            "scraper_index": scraper_index,
                            "consecutive_idle": consecutive_idle,
                            "all_scrapers_idle_rounds": all_scrapers_idle_rounds,
                            "scraped_count": current_scraped_count
                        })
                        if all_scrapers_idle_rounds >= ALL_IDLE_ROUNDS_THRESHOLD:
                            stop_flag.set()
                            return
                    await asyncio.sleep(0.5)
                    continue
                # Reset idle state when we find work
                consecutive_idle = 0
                async with lock:
                    scraper_idle_flags[scraper_index] = False
                    all_scrapers_idle_rounds = 0  # Reset global idle counter
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

                    # Log how many internal links were found
                    internal_links = rec.get("links_internal", [])
                    _progress({
                        "event": "links_found",
                        "url": url,
                        "internal_links_count": len(internal_links),
                        "sample_links": internal_links[:5] if internal_links else []
                    })

                    links_added = 0
                    for link in internal_links:
                        ln = norm_crawl_url(link)
                        if not ln:
                            continue
                        if _is_blog_url(ln):
                            _progress({"event": "link_skipped", "url": ln, "reason": "blog_url"})
                            continue
                        async with lock:
                            if ln in discovered:
                                continue  # Already discovered
                            if should_skip_url(ln):
                                _progress({"event": "link_skipped", "url": ln, "reason": "skip_extension"})
                                continue
                            if respect_robots and robots_parser and not robots_parser.can_fetch("*", ln):
                                _progress({"event": "link_skipped", "url": ln, "reason": "robots_blocked"})
                                continue
                            to_visit.append(ln)
                            discovered.add(ln)
                            links_added += 1
                            _progress({"event": "link_added", "url": ln})

                    _progress({"event": "scraper_links_summary", "url": url, "links_added": links_added, "total_discovered": len(discovered), "total_scraped": len(scraped_urls)})
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


def _create_robots_parser(base_url: str) -> urllib.robotparser.RobotFileParser | None:
    """
    Create a robots parser with proper User-Agent.
    Returns None if robots.txt can't be fetched or parsed.
    """
    try:
        robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PlaywrightCrawler/1.0)",
        }
        req = urllib.request.Request(robots_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8", errors="replace")

        # If robots.txt has no Disallow rules, it means everything is allowed
        # Python's RobotFileParser incorrectly returns False when there are no rules
        has_disallow = "disallow" in content.lower()
        if not has_disallow:
            _progress({"event": "robots_info", "message": "robots.txt has no Disallow rules, allowing all URLs"})
            return None  # None means no restrictions

        # Parse the robots.txt
        robots_parser = urllib.robotparser.RobotFileParser()
        robots_parser.parse(content.splitlines())
        return robots_parser
    except Exception as e:
        _progress({"event": "robots_info", "message": f"Could not fetch robots.txt: {e}, allowing all URLs"})
        return None  # If we can't fetch robots.txt, allow everything


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

    robots_parser = None
    if respect_robots:
        robots_parser = _create_robots_parser(base_url)

    skip_set = {norm_crawl_url(u) for u in (skip_urls or []) if norm_crawl_url(u)}

    if parallel:
        if async_playwright is None:
            raise RuntimeError("playwright async_api required for parallel crawl")
        coro = _crawl_parallel_async(
            base_url,
            base_domain,
            max_pages,
            max_depth,
            respect_robots,
            robots_parser,
            t_start,
            headless,
            resume=resume_checkpoint,
            skip_urls=skip_set,
            max_parallel_pages=max_parallel_pages,
        )
        try:
            return asyncio.run(coro)
        except RuntimeError:
            # Some environments can have an active event loop already; run in a fresh loop/thread.
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

    scraped_urls: list[str] = []
    failed_list: list[dict] = []
    # Only collect full page data for small crawls (<=5 pages) to avoid memory issues
    collect_pages = max_pages <= 5
    pages_data: list[dict] = []
    visited = set()
    queue = deque([(base_url, 0)])

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
                    "content_hash": hashlib.sha256(extract_text_from_html(html).encode("utf-8")).hexdigest(),
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
                        ln = (link.rstrip("/") or link)
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


def main():
    parser = argparse.ArgumentParser(description="Playwright recursive website crawler")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--parallel", action="store_true", default=True)
    parser.add_argument("--no-parallel", action="store_false", dest="parallel")
    parser.add_argument("--max-parallel-pages", type=int, default=1, help="Max pages to scrape in parallel (default: 1)")
    parser.add_argument("--no-robots", action="store_true")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument(
        "--job-json",
        default=None,
        help="Optional JSON file with resumeCheckpoint and skipUrls for crawl resume",
    )
    args = parser.parse_args()

    if not HAS_PLAYWRIGHT:
        print(json.dumps({"error": "playwright_not_installed"}), flush=True)
        return

    job: dict = {}
    if args.job_json:
        try:
            with open(args.job_json, encoding="utf-8") as jf:
                job = json.load(jf)
            if not isinstance(job, dict):
                job = {}
        except Exception:
            job = {}

    resume_ck = job.get("resumeCheckpoint") if isinstance(job.get("resumeCheckpoint"), dict) else None
    skip_list = job.get("skipUrls") if isinstance(job.get("skipUrls"), list) else None

    result = crawl_with_playwright(
        args.url,
        args.max_pages,
        args.max_depth,
        respect_robots=not args.no_robots,
        headless=not args.no_headless,
        deep=args.deep,
        parallel=getattr(args, "parallel", False),
        resume_checkpoint=resume_ck,
        skip_urls=[str(u) for u in skip_list] if skip_list else None,
        max_parallel_pages=args.max_parallel_pages,
    )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
