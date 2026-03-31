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
        if lp.netloc.lower().endswith(base_domain) or lp.netloc.lower() == base_domain:
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
            if netloc == base_domain or netloc.endswith("." + base_domain):
                if not should_skip_url(u):
                    urls.append(u)
        if urls:
            break
    return list(dict.fromkeys(urls))


def _is_blog_url(url: str) -> bool:
    return "blog" in url.lower()


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

        internal_links, _ = parse_links(html, url_norm, base_domain)
        content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()

        return {
            "url": url_norm,
            "depth": depth,
            "status_code": status_code,
            "title": (await page.title()) if hasattr(page, "title") else "",
            "meta_description": "",
            "meta_keywords": "",
            "elements": elements,
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
        }
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
        for u in _fetch_sitemap_urls(base_url, base_domain)[:500]:
            un = norm_crawl_url(u)
            if not un:
                continue
            if un not in discovered and not should_skip_url(un) and not _is_blog_url(un):
                if not respect_robots or not robots_parser or robots_parser.can_fetch("*", un):
                    to_visit.append(un)

    lock = asyncio.Lock()
    stop_flag = asyncio.Event()
    discovery_idle_count = 0
    scraper_idle_count = 0
    IDLE_THRESHOLD = 2

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
        context_disc = await browser.new_context(viewport={"width": 1280, "height": 900})
        context_scrape = await browser.new_context(viewport={"width": 1280, "height": 900})

        async def discovery_coro():
            nonlocal discovery_idle_count
            while not stop_flag.is_set():
                url = None
                async with lock:
                    if len(discovered) >= max_pages * 2:
                        return
                    if to_visit:
                        url = to_visit.popleft()
                        if url not in discovered:
                            discovered.add(url)
                        else:
                            url = None
                if url is None:
                    discovery_idle_count += 1
                    if discovery_idle_count >= IDLE_THRESHOLD and scraper_idle_count >= IDLE_THRESHOLD:
                        stop_flag.set()
                        return
                    await asyncio.sleep(0.3)
                    continue
                discovery_idle_count = 0
                if _is_blog_url(url):
                    continue
                page = await context_disc.new_page()
                try:
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=12000)
                    except PWTimeoutAsync:
                        try:
                            await page.goto(url, wait_until="load", timeout=10000)
                        except PWTimeoutAsync:
                            pass
                    await asyncio.sleep(1.0)
                    html = await page.content()
                    internal, _ = parse_links(html, url, base_domain)
                    async with lock:
                        for link in internal:
                            ln = norm_crawl_url(link)
                            if not ln:
                                continue
                            if ln not in discovered and not should_skip_url(ln) and not _is_blog_url(ln):
                                if not respect_robots or not robots_parser or robots_parser.can_fetch("*", ln):
                                    to_visit.append(ln)
                    _progress({"event": "discovered", "url": url})
                except Exception:
                    pass
                finally:
                    await page.close()
                    await asyncio.sleep(0.2)

        async def scraper_coro():
            nonlocal scraped_urls, failed_list, scraper_idle_count
            while not stop_flag.is_set():
                async with lock:
                    if len(scraped_urls) >= max_pages:
                        stop_flag.set()
                        return
                    to_scrape = [u for u in discovered if u not in scraped and not _is_blog_url(u)]
                    if not to_scrape:
                        url = None
                    else:
                        url = to_scrape[0]
                        scraped.add(url)
                if url is None:
                    scraper_idle_count += 1
                    if discovery_idle_count >= IDLE_THRESHOLD and scraper_idle_count >= IDLE_THRESHOLD:
                        stop_flag.set()
                        return
                    await asyncio.sleep(0.5)
                    continue
                scraper_idle_count = 0
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
                    _progress({"event": "page_data", **rec})
                    await _emit_checkpoint()
                    for link in rec.get("links_internal", []):
                        ln = norm_crawl_url(link)
                        if not ln or _is_blog_url(ln):
                            continue
                        async with lock:
                            if ln not in discovered and not should_skip_url(ln):
                                if not respect_robots or not robots_parser or robots_parser.can_fetch("*", ln):
                                    to_visit.append(ln)
                                    discovered.add(ln)
                else:
                    async with lock:
                        failed_list.append({"url": url, "error": "scrape_failed"})
                await asyncio.sleep(0.2)

        await asyncio.wait_for(asyncio.gather(discovery_coro(), scraper_coro()), timeout=3600)
        await context_disc.close()
        await context_scrape.close()
        await browser.close()

    return {
        "base_url": base_url,
        "scraped_urls": scraped_urls,
        "failed_urls": failed_list,
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
) -> dict:
    t_start = time.time()

    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    robots_parser = None
    if respect_robots:
        try:
            robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
            robots_parser = urllib.robotparser.RobotFileParser()
            robots_parser.set_url(robots_url)
            robots_parser.read()
        except Exception:
            robots_parser = None

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
    )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
