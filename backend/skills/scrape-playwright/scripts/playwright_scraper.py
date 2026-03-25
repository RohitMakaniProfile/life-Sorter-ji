#!/usr/bin/env python3
"""
biz-scrape-playwright: Playwright-based recursive website crawler.
Renders JavaScript, handles SPAs, discovers dynamically loaded content.
Requires: pip install playwright && playwright install chromium

Output JSON schema: identical to bs4_scraper.py for compatibility with context-store.
Additional fields per page:
  - "js_rendered": true
  - "network_requests": [str]  # XHR/fetch URLs captured (API endpoints)
  - "local_storage_keys": [str]
  - "cookies_names": [str]
  - "tech_stack": { "detected", "signals", "method", "retire" }
    DOM heuristics plus optional Retire.js jsrepository.json matches on script responses (downloaded + cached).
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


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from bs4_scraper for standalone use)
# ---------------------------------------------------------------------------

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".tar", ".gz", ".exe", ".dmg",
    ".css", ".woff", ".woff2", ".ttf", ".ico",
    ".xml", ".json",  # sitemaps, API responses — we only scrape HTML pages
}


def should_skip_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""
    return ext in SKIP_EXTENSIONS


def extract_text_from_html(html: str) -> str:
    """Simple regex text extraction."""
    # Remove scripts, styles
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
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


_TECH_STACK_EVAL_JS = r"""
() => {
  const signals = {};
  const add = (name, reason) => {
    if (!signals[name]) signals[name] = [];
    if (signals[name].indexOf(reason) === -1) signals[name].push(reason);
  };

  const html = (document.documentElement && document.documentElement.outerHTML) || "";
  const headHtml = (document.head && document.head.innerHTML) || "";
  const scriptSrcs = Array.from(document.scripts || []).map((s) => s.src || "").join(" ");
  const scriptInline = Array.from(document.scripts || [])
    .map((s) => (s.textContent || "").slice(0, 4000))
    .join(" ");
  const linkHrefs = Array.from(document.querySelectorAll('link[rel="stylesheet"],link[rel="preload"]'))
    .map((l) => l.href || "")
    .join(" ");
  const preloadHints = Array.from(
    document.querySelectorAll('link[rel="modulepreload"],link[rel="preload"]'),
  )
    .map((l) => l.href || "")
    .join(" ");
  const combinedAssets = scriptSrcs + " " + linkHrefs + " " + preloadHints;

  try {
    const gen = document.querySelector('meta[name="generator"]');
    if (gen) {
      const gc = ((gen.getAttribute("content") || "") + "").toLowerCase();
      if (gc.includes("next.js") || gc.includes("nextjs")) add("nextjs", "meta_generator");
      if (gc.includes("gatsby")) add("gatsby", "meta_generator");
      if (gc.includes("nuxt")) add("nuxt", "meta_generator");
      if (gc.includes("astro")) add("astro", "meta_generator");
      if (gc.includes("wordpress")) add("wordpress", "meta_generator");
      if (gc.includes("webflow")) add("webflow", "meta_generator");
      if (gc.includes("framer")) add("framer", "meta_generator");
    }
  } catch (e) {}

  try {
    for (const s of Array.from(document.scripts || [])) {
      const u = ((s.src || "") + "").toLowerCase();
      if (!u) continue;
      if (u.includes("/_next/") || u.includes("_next/static")) add("nextjs", "script_src");
      if (u.includes("chunks/webpack-") || u.includes("/webpack-")) add("nextjs", "webpack_chunk_path");
      if (u.includes("main-app-") || u.includes("main-app.")) add("nextjs", "next_main_app_chunk");
      if (u.includes("framerusercontent.com") || u.includes(".framer.")) add("framer", "script_host");
      if (u.includes("webflow")) add("webflow", "script_path");
    }
  } catch (e) {}

  try {
    if (document.getElementById("__next") || html.includes('id="__next"')) {
      add("nextjs", "next_root_div");
    }
    if (html.includes("__next_f")) {
      add("nextjs", "next_app_router_flight");
    }
    if (typeof window !== "undefined" && window.__next_f && Array.isArray(window.__next_f)) {
      add("nextjs", "next_f_global");
    }
  } catch (e) {}

  try {
    if (document.getElementById("__NEXT_DATA__") || typeof window.__NEXT_DATA__ !== "undefined") {
      add("nextjs", "__NEXT_DATA__");
    }
    if (scriptSrcs.includes("/_next/") || scriptSrcs.includes("_next/static") || html.includes("/_next/static")) {
      add("nextjs", "next_static_path");
    }
  } catch (e) {}

  try {
    if (
      !!document.querySelector("[class*='nextjs']") ||
      !!document.querySelector("[data-nextjs-screen]")
    ) {
      add("nextjs", "next_data_attr");
    }
  } catch (e) {}

  try {
    if (typeof window.__NUXT__ !== "undefined" || document.getElementById("__NUXT__")) {
      add("nuxt", "nuxt_global");
    }
  } catch (e) {}

  try {
    if (typeof window.__remixContext !== "undefined") {
      add("remix", "remix_context");
    }
  } catch (e) {}

  try {
    if (typeof window.__GATSBY !== "undefined" || html.includes("___gatsby") || html.includes("gatsby-browser")) {
      add("gatsby", "gatsby_marker");
    }
  } catch (e) {}

  try {
    const ng = document.querySelector("[ng-version]") || document.documentElement.getAttribute("ng-version");
    if (ng) {
      add("angular", "ng_version_attr");
    }
    if (html.includes("ng-version=") || html.includes('ng-app="') || html.includes("ng-app=")) {
      add("angular", "angular_dom");
    }
  } catch (e) {}

  try {
    if (
      document.querySelector("astro-island, [data-astro-cid], [data-astro-transition], [data-astro-reload]") ||
      html.includes("data-astro-") ||
      combinedAssets.includes("astro")
    ) {
      add("astro", "astro_marker");
    }
  } catch (e) {}

  try {
    if (typeof window.__VUE__ !== "undefined") {
      add("vue", "vue_global");
    }
    if (html.includes("data-v-") && (html.includes("__VUE") || scriptInline.includes("vue"))) {
      add("vue", "vue_dom_or_bundle");
    }
  } catch (e) {}

  try {
    if (typeof window.__REACT_DEVTOOLS_GLOBAL_HOOK__ !== "undefined") {
      add("react", "react_devtools_hook");
    }
    if (document.querySelector("[data-reactroot], [data-react-helmet]")) {
      add("react", "react_dom_attr");
    }
    if (scriptInline.includes("react-dom") || scriptInline.includes("ReactDOM")) {
      add("react", "inline_react");
    }
    if (combinedAssets.includes("react") && (combinedAssets.includes("chunk") || combinedAssets.includes("static"))) {
      add("react", "script_name_hint");
    }
  } catch (e) {}

  try {
    if (scriptSrcs.includes("/@vite/") || scriptSrcs.includes("@vite/client") || html.includes("@vite/client")) {
      add("vite", "vite_client");
    }
  } catch (e) {}

  try {
    if (html.includes("svelte-") || scriptSrcs.includes("svelte") || scriptInline.includes("svelte")) {
      add("svelte", "svelte_marker");
    }
  } catch (e) {}

  try {
    if (typeof window.webpackChunk !== "undefined" || typeof window.__webpack_require__ !== "undefined") {
      add("webpack", "webpack_global");
    }
  } catch (e) {}

  try {
    if (
      scriptSrcs.includes("tailwindcss") ||
      scriptSrcs.includes("cdn.tailwindcss.com") ||
      linkHrefs.includes("tailwind") ||
      html.includes("tailwindcss")
    ) {
      add("tailwindcss", "tailwind_asset");
    }
  } catch (e) {}

  try {
    if (signals.nextjs && !signals.react) {
      add("react", "typical_nextjs_bundle");
    }
  } catch (e) {}

  const detected = Object.keys(signals).sort();
  return { detected, signals, method: "dom_and_global_heuristic" };
}
"""


def detect_tech_stack_from_page(page) -> dict:
    """Best-effort framework/CSS-tool hints from the live page (sync Playwright page)."""
    try:
        data = page.evaluate(_TECH_STACK_EVAL_JS)
        if isinstance(data, dict):
            return {
                "detected": list(data.get("detected") or []),
                "signals": data.get("signals") if isinstance(data.get("signals"), dict) else {},
                "method": str(data.get("method") or "dom_and_global_heuristic"),
            }
    except Exception:
        pass
    return {"detected": [], "signals": {}, "method": "dom_and_global_heuristic"}


async def detect_tech_stack_from_page_async(page) -> dict:
    """Best-effort framework hints (async Playwright page)."""
    try:
        data = await page.evaluate(_TECH_STACK_EVAL_JS)
        if isinstance(data, dict):
            return {
                "detected": list(data.get("detected") or []),
                "signals": data.get("signals") if isinstance(data.get("signals"), dict) else {},
                "method": str(data.get("method") or "dom_and_global_heuristic"),
            }
    except Exception:
        pass
    return {"detected": [], "signals": {}, "method": "dom_and_global_heuristic"}


def _response_looks_like_script(resp) -> bool:
    try:
        req = resp.request
        url = ((getattr(resp, "url", None) or "") or "").split("?")[0].lower()
        headers = getattr(resp, "headers", None) or {}
        ct = (headers.get("content-type") or "").lower()
        if getattr(req, "resource_type", None) == "script":
            return True
        if "javascript" in ct or "ecmascript" in ct:
            return True
        if url.endswith(".js"):
            return True
        if "/_next/static/" in url or "/chunks/" in url:
            return True
    except Exception:
        pass
    return False


def _collect_script_sample_sync(resp) -> dict | None:
    try:
        if not _response_looks_like_script(resp):
            return None
        url = resp.url
        cl = (getattr(resp, "headers", None) or {}).get("content-length")
        body: str | None = None
        if cl:
            try:
                if int(cl) > 900_000:
                    return {"url": url, "body": None}
            except ValueError:
                pass
            try:
                body = resp.text()
            except Exception:
                body = None
            if body and len(body) > 450_000:
                body = body[:450_000]
        return {"url": url, "body": body}
    except Exception:
        return None


def _attach_script_collector_sync(page, bucket: list) -> None:
    def on_response(resp):
        s = _collect_script_sample_sync(resp)
        if s:
            bucket.append(s)

    page.on("response", on_response)


def _attach_script_collector_async(page, bucket: list) -> None:
    loop = asyncio.get_running_loop()

    async def capture(resp):
        try:
            if not _response_looks_like_script(resp):
                return
            url = resp.url
            cl = (getattr(resp, "headers", None) or {}).get("content-length")
            body: str | None = None
            if cl:
                try:
                    if int(cl) > 900_000:
                        bucket.append({"url": url, "body": None})
                        return
                except ValueError:
                    pass
                try:
                    body = await resp.text()
                except Exception:
                    body = None
                if body and len(body) > 450_000:
                    body = body[:450_000]
                bucket.append({"url": url, "body": body})
            else:
                bucket.append({"url": url, "body": None})
        except Exception:
            pass

    def on_response(resp):
        loop.create_task(capture(resp))

    page.on("response", on_response)


def merge_retire_into_tech_stack(tech_stack: dict, script_samples: list) -> dict:
    """Enrich tech_stack with Retire.js rule hits from captured script URLs/bodies."""
    out = dict(tech_stack)
    try:
        from retire_matcher import DEFAULT_RETIRE_URL, match_script_samples, retire_libraries_from_hits

        hits = match_script_samples(script_samples)
        libs = retire_libraries_from_hits(hits)
        src = os.getenv("RETIRE_JSREPO_URL", "").strip() or DEFAULT_RETIRE_URL
        out["retire"] = {
            "ruleset": "RetireJS/jsrepository.json",
            "source_url": src[:240],
            "libraries": libs,
            "hits": hits[:25],
        }
        dom = set(out.get("detected") or [])
        out["detected"] = sorted(dom | set(libs))
    except Exception as e:
        out["retire"] = {
            "ruleset": "RetireJS/jsrepository.json",
            "error": str(e)[:240],
            "libraries": [],
            "hits": [],
        }
    return out


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


def parse_headings(html: str, level: int) -> list[str]:
    tag = f"h{level}"
    results = []
    for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.I | re.S):
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            results.append(text)
    return results


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
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                t = obj.get("@type")
                if isinstance(t, str): types.append(t)
                elif isinstance(t, list): types.extend(t)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        t = item.get("@type")
                        if isinstance(t, str): types.append(t)
        except Exception:
            pass
    return types


# ---------------------------------------------------------------------------
# Progress: one JSON object per line to stderr for the loader to stream to frontend
# ---------------------------------------------------------------------------

def _progress(obj: dict) -> None:
    # Explicit persistence hint for backend:
    # - page_data: real scraped page payload (store in DB)
    # - everything else: runtime status/info only (do not store)
    if "streamKind" not in obj:
        evt = str(obj.get("event") or "").strip().lower()
        obj["streamKind"] = "data" if evt == "page_data" else "info"
    print(json.dumps(obj), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Sitemap discovery (so we find all pages even when homepage has few links)
# ---------------------------------------------------------------------------

def _fetch_sitemap_urls(base_url: str, base_domain: str) -> list[str]:
    """Fetch URLs from sitemap.xml / sitemap_index.xml / sitemap.txt (same domain only)."""
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
        # <loc>URL</loc> for XML sitemaps
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


# ---------------------------------------------------------------------------
# Playwright crawler
# ---------------------------------------------------------------------------

def _scrape_single_page(context, url_norm: str, depth: int, base_domain: str,
                         robots_parser, respect_robots: bool) -> dict | None:
    """Scrape one page fully. Returns page_record or None on failure."""
    network_requests = []
    script_samples: list[dict] = []

    def on_request(req):
        if req.resource_type in ("xhr", "fetch"):
            network_requests.append(req.url)

    page = context.new_page()
    page.on("request", on_request)
    _attach_script_collector_sync(page, script_samples)
    try:
        try:
            resp = page.goto(url_norm, wait_until="networkidle", timeout=30000)
        except PWTimeout:
            resp = None
        status_code = resp.status if resp else 0
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PWTimeout:
            pass
        html = page.content()
        title = page.title()
        meta_desc = ""
        try:
            meta_desc = page.eval_on_selector('meta[name="description"]', 'el => el.getAttribute("content") || ""') or ""
        except Exception:
            pass
        meta_keywords = ""
        try:
            meta_keywords = page.eval_on_selector('meta[name="keywords"]', 'el => el.getAttribute("content") || ""') or ""
        except Exception:
            pass
        robots_meta = ""
        try:
            robots_meta = page.eval_on_selector('meta[name="robots"]', 'el => el.getAttribute("content") || ""') or ""
        except Exception:
            pass
        canonical = ""
        try:
            canonical = page.eval_on_selector('link[rel="canonical"]', 'el => el.getAttribute("href") || ""') or ""
        except Exception:
            pass
        local_storage_keys = []
        try:
            local_storage_keys = page.evaluate("Object.keys(localStorage)")
        except Exception:
            pass
        cookie_names = [c["name"] for c in context.cookies()]

        internal_links, _ = parse_links(html, url_norm, base_domain)
        body_text = extract_text_from_html(html)
        elements = extract_content_elements_from_page(page, html)
        content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
        tech_stack = merge_retire_into_tech_stack(
            detect_tech_stack_from_page(page), script_samples
        )

        return {
            "url": url_norm,
            "depth": depth,
            "status_code": status_code,
            "title": title,
            "meta_description": meta_desc,
            "meta_keywords": meta_keywords,
            "elements": elements,
            "links_internal": internal_links,
            "schema_types": parse_schema_types(html),
            "canonical": canonical,
            "robots": robots_meta,
            "content_hash": content_hash,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "js_rendered": True,
            "network_requests": list(dict.fromkeys(network_requests))[:30],
            "local_storage_keys": local_storage_keys[:20],
            "cookie_names": cookie_names[:20],
            "links_external": [],
            "tech_stack": tech_stack,
        }
    except Exception:
        return None
    finally:
        page.close()
        time.sleep(0.3)


def _discover_urls_phase(context, base_url: str, base_domain: str, max_depth: int,
                         respect_robots: bool, robots_parser, max_pages: int = 9999) -> list[str]:
    """Phase 1: Discover same-domain URLs via sitemap + BFS (stops when we have enough)."""
    visited = set()
    queue = deque([(base_url, 0)])
    # Seed with sitemap URLs (skip blog URLs to avoid thousands of blog links)
    sitemap_urls = _fetch_sitemap_urls(base_url, base_domain)
    for su in sitemap_urls[:500]:
        snorm = (su.rstrip("/") or su)
        if snorm not in visited and not should_skip_url(snorm) and not _is_blog_url(snorm):
            if not respect_robots or not robots_parser or robots_parser.can_fetch("*", snorm):
                queue.append((snorm, 1))
    discovered: list[str] = []

    while queue and len(discovered) < max_pages:
        url, depth = queue.popleft()
        url_norm = url.rstrip("/") or url

        if url_norm in visited:
            continue
        visited.add(url_norm)

        if should_skip_url(url_norm):
            continue
        if _is_blog_url(url_norm):
            continue
        if respect_robots and robots_parser and not robots_parser.can_fetch("*", url_norm):
            continue
        if depth > max_depth:
            continue

        discovered.append(url_norm)
        _progress({"event": "discovered", "url": url_norm, "index": len(discovered)})

        page = context.new_page()
        try:
            # Wait for full load so JS-rendered links appear in DOM (SPA); fallback to "load" on timeout
            try:
                page.goto(url_norm, wait_until="networkidle", timeout=12000)
            except PWTimeout:
                try:
                    page.goto(url_norm, wait_until="load", timeout=10000)
                except PWTimeout:
                    pass
            time.sleep(1.0)  # allow client-side routing / dynamic links
            html = page.content()
            internal, _ = parse_links(html, url_norm, base_domain)
            if depth < max_depth:
                for link in internal:
                    ln = (link.rstrip("/") or link)
                    if ln not in visited and not _is_blog_url(ln):
                        queue.append((ln, depth + 1))
        except Exception:
            pass
        finally:
            page.close()
            time.sleep(0.2)

    return discovered


# ---------------------------------------------------------------------------
# Parallel crawl: discovery + scraper as async tasks (same thread, Playwright-safe)
# ---------------------------------------------------------------------------

def _is_blog_url(url: str) -> bool:
    """True if URL should be skipped by scraper (contains 'blog')."""
    return "blog" in url.lower()


async def _scrape_single_page_async(context, url_norm: str, depth: int, base_domain: str,
                                     robots_parser, respect_robots: bool) -> dict | None:
    """Async: scrape one page fully. Returns page_record or None on failure."""
    network_requests = []
    script_samples: list[dict] = []

    def on_request(req):
        if req.resource_type in ("xhr", "fetch"):
            network_requests.append(req.url)

    page = await context.new_page()
    page.on("request", on_request)
    _attach_script_collector_async(page, script_samples)
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
        title = await page.title()
        meta_desc = ""
        try:
            meta_desc = await page.eval_on_selector('meta[name="description"]', 'el => el.getAttribute("content") || ""') or ""
        except Exception:
            pass
        meta_keywords = ""
        try:
            meta_keywords = await page.eval_on_selector('meta[name="keywords"]', 'el => el.getAttribute("content") || ""') or ""
        except Exception:
            pass
        robots_meta = ""
        try:
            robots_meta = await page.eval_on_selector('meta[name="robots"]', 'el => el.getAttribute("content") || ""') or ""
        except Exception:
            pass
        canonical = ""
        try:
            canonical = await page.eval_on_selector('link[rel="canonical"]', 'el => el.getAttribute("href") || ""') or ""
        except Exception:
            pass
        local_storage_keys = []
        try:
            local_storage_keys = await page.evaluate("Object.keys(localStorage)")
        except Exception:
            pass
        cookie_names = [c["name"] for c in await context.cookies()]

        internal_links, _ = parse_links(html, url_norm, base_domain)
        body_text = extract_text_from_html(html)
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
            else:
                elements = []
        except Exception:
            elements = []
        if not elements:
            elements = extract_content_elements(html)
        content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
        tech_stack = merge_retire_into_tech_stack(
            await detect_tech_stack_from_page_async(page), script_samples
        )

        return {
            "url": url_norm,
            "depth": depth,
            "status_code": status_code,
            "title": title,
            "meta_description": meta_desc,
            "meta_keywords": meta_keywords,
            "elements": elements,
            "links_internal": internal_links,
            "schema_types": parse_schema_types(html),
            "canonical": canonical,
            "robots": robots_meta,
            "content_hash": content_hash,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "js_rendered": True,
            "network_requests": list(dict.fromkeys(network_requests))[:30],
            "local_storage_keys": local_storage_keys[:20],
            "cookie_names": cookie_names[:20],
            "links_external": [],
            "tech_stack": tech_stack,
        }
    except Exception:
        return None
    finally:
        await asyncio.sleep(0.4)
        await page.close()
        await asyncio.sleep(0.3)


async def _crawl_parallel_async(
    base_url: str,
    base_domain: str,
    max_pages: int,
    max_depth: int,
    respect_robots: bool,
    robots_parser,
    t_start: float,
    headless: bool,
) -> dict:
    """
    Two async tasks (same thread):
    1) Discovery: pops from to_visit, visits page, extracts links → to_visit + discovered, emits "discovered".
    2) Scraper: picks from (discovered - scraped) excluding 'blog' URLs, scrapes one, emits "page_data", adds new links to to_visit, marks scraped.
    Uses async_playwright so both run concurrently without threading (Playwright sync API is not thread-safe).
    """
    to_visit = deque()
    discovered = set()
    scraped = set()  # URLs we've finished scraping (for stop condition)
    scraped_urls = []  # ordered list for result; full page data streamed via progress only
    failed_list = []
    lock = asyncio.Lock()
    stop_flag = asyncio.Event()
    # Close-up: when both discovery and scraper are idle (nothing to do), stop after this many idle cycles
    discovery_idle_count = 0
    scraper_idle_count = 0
    IDLE_THRESHOLD = 2

    # Seed discovery (skip blog URLs so we don't spend time on thousands of blog links)
    to_visit.append(base_url)
    for u in _fetch_sitemap_urls(base_url, base_domain)[:500]:
        u = (u.rstrip("/") or u)
        if u not in discovered and not should_skip_url(u) and not _is_blog_url(u):
            if not respect_robots or not robots_parser or robots_parser.can_fetch("*", u):
                to_visit.append(u)

    _progress({"event": "started", "parallel": True})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_disc = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        context_scrape = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )

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
                # Skip visiting blog pages in discovery (saves time; we never scrape them anyway)
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
                            ln = (link.rstrip("/") or link)
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
                    to_scrape = [
                        u for u in discovered
                        if u not in scraped and not _is_blog_url(u)
                    ]
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
                rec = await _scrape_single_page_async(
                    context_scrape, url, 0, base_domain, robots_parser, respect_robots
                )
                if rec:
                    async with lock:
                        scraped_urls.append(url)
                    # Stream full page so Node can store in DB; no in-memory accumulation
                    _progress({"event": "page_data", **rec})
                    for link in rec.get("links_internal", []):
                        ln = (link.rstrip("/") or link)
                        if _is_blog_url(ln):
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

        await asyncio.wait_for(
            asyncio.gather(discovery_coro(), scraper_coro()),
            timeout=3600,
        )

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
            "crawl_duration_s": round(time.time() - t_start, 2),
        },
    }


def _crawl_parallel(
    base_url: str,
    base_domain: str,
    max_pages: int,
    max_depth: int,
    respect_robots: bool,
    robots_parser,
    t_start: float,
    headless: bool,
) -> dict:
    """Run the async parallel crawl from sync context."""
    if async_playwright is None:
        raise RuntimeError("playwright async_api required for parallel crawl; pip install playwright")
    return asyncio.run(_crawl_parallel_async(
        base_url, base_domain, max_pages, max_depth,
        respect_robots, robots_parser, t_start, headless,
    ))


def crawl_with_playwright(base_url: str, max_pages: int, max_depth: int,
                          respect_robots: bool, headless: bool, deep: bool = False,
                          parallel: bool = False) -> dict:
    t_start = time.time()

    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    # Robots parser
    robots_parser = None
    robots_txt = ""
    if respect_robots:
        try:
            robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
            robots_parser = urllib.robotparser.RobotFileParser()
            robots_parser.set_url(robots_url)
            robots_parser.read()
            with urllib.request.urlopen(robots_url, timeout=8) as r:
                robots_txt = r.read().decode("utf-8", errors="replace")[:5000]
        except Exception:
            # If robots.txt is blocked/unavailable (common behind WAF), do not block crawl.
            robots_parser = None
            robots_txt = ""

    scraped_urls: list[str] = []
    failed_list: list[dict] = []  # [{"url": str, "error": str}, ...]
    failed = 0
    skipped = 0
    visited = set()
    queue = deque([(base_url, 0)])

    if parallel:
        return _crawl_parallel(
            base_url, base_domain, max_pages, max_depth,
            respect_robots, robots_parser, t_start, headless,
        )

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=headless)
        except Exception as e:
            return {
                "base_url": base_url,
                "scraped_urls": [],
                "failed_urls": [],
                "error": "playwright_launch_failed",
                "error_message": f"Chromium launch failed: {e}. Run: playwright install chromium",
                "stats": {"total_pages": 0, "failed_pages": 0, "skipped_pages": 0, "crawl_duration_s": 0},
            }
        _progress({"event": "started"})
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )

        if deep:
            # Two-phase: 1) discover URLs (cap at max_pages for faster runs), 2) scrape each
            discovered = _discover_urls_phase(
                context, base_url, base_domain, max_depth, respect_robots, robots_parser, max_pages
            )
            _progress({"event": "discovery_done", "total_pages": len(discovered)})

            to_scrape = [u for u in discovered if not _is_blog_url(u)][:max_pages]
            scraped_urls = []
            for idx, url_norm in enumerate(to_scrape):
                _progress({"event": "page", "url": url_norm, "status": "scraping", "index": idx + 1, "total": len(to_scrape)})
                rec = _scrape_single_page(context, url_norm, 0, base_domain, robots_parser, respect_robots)
                if rec:
                    scraped_urls.append(url_norm)
                    _progress({"event": "page_data", **rec})
                    _progress({"event": "page", "url": url_norm, "status": "done", "index": idx + 1, "total": len(to_scrape)})
                else:
                    failed += 1
                    failed_list.append({"url": url_norm, "error": "scrape_failed"})
                    _progress({"event": "page", "url": url_norm, "status": "failed", "index": idx + 1, "total": len(to_scrape)})
            browser.close()
            return {
                "base_url": base_url,
                "scraped_urls": scraped_urls,
                "failed_urls": failed_list,
                "stats": {
                    "total_pages": len(scraped_urls),
                    "failed_pages": failed,
                    "skipped_pages": 0,
                    "crawl_duration_s": round(time.time() - t_start, 2),
                },
            }

        scraped_urls = []
        while queue and len(scraped_urls) < max_pages:
            url, depth = queue.popleft()
            url_norm = url.rstrip("/") or url

            if url_norm in visited:
                continue
            visited.add(url_norm)

            if should_skip_url(url_norm):
                skipped += 1
                continue

            if respect_robots and robots_parser and not robots_parser.can_fetch("*", url_norm):
                skipped += 1
                continue

            if depth > max_depth:
                skipped += 1
                continue

            scraped_so_far = len(scraped_urls) + 1
            _progress({"event": "page", "url": url_norm, "status": "scraping", "scraped": scraped_so_far})

            # Capture network requests
            network_requests = []
            _script_samples: list[dict] = []

            def on_request(req):
                if req.resource_type in ("xhr", "fetch"):
                    network_requests.append(req.url)

            page = context.new_page()
            page.on("request", on_request)
            _attach_script_collector_sync(page, _script_samples)

            try:
                # Try to wait for network to go idle, but do not treat a timeout
                # as a hard failure — we will still scrape whatever content is
                # available on the page.
                try:
                    resp = page.goto(url_norm, wait_until="networkidle", timeout=30000)
                except PWTimeout as e:
                    # Network never went idle within 30s; proceed with partial
                    # content instead of marking this URL as failed.
                    resp = None
                    timeout_err = str(e)
                else:
                    timeout_err = ""

                status_code = resp.status if resp else 0

                # Wait for dynamic content (best-effort)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PWTimeout:
                    pass

                html = page.content()
                title = page.title()

                # Meta description
                meta_desc = ""
                try:
                    meta_desc = page.eval_on_selector(
                        'meta[name="description"]', 'el => el.getAttribute("content") || ""'
                    ) or ""
                except Exception:
                    pass

                meta_keywords = ""
                try:
                    meta_keywords = page.eval_on_selector(
                        'meta[name="keywords"]', 'el => el.getAttribute("content") || ""'
                    ) or ""
                except Exception:
                    pass

                robots_meta = ""
                try:
                    robots_meta = page.eval_on_selector(
                        'meta[name="robots"]', 'el => el.getAttribute("content") || ""'
                    ) or ""
                except Exception:
                    pass

                canonical = ""
                try:
                    canonical = page.eval_on_selector(
                        'link[rel="canonical"]', 'el => el.getAttribute("href") || ""'
                    ) or ""
                except Exception:
                    pass

                # Local storage keys
                local_storage_keys = []
                try:
                    local_storage_keys = page.evaluate("Object.keys(localStorage)")
                except Exception:
                    pass

                # Cookie names
                cookie_names = [c["name"] for c in context.cookies()]

                internal_links, external_links = parse_links(html, url_norm, base_domain)
                body_text = extract_text_from_html(html)
                elements = extract_content_elements_from_page(page, html)
                content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
                tech_stack = merge_retire_into_tech_stack(
                    detect_tech_stack_from_page(page), _script_samples
                )

                page_record = {
                    "url": url_norm,
                    "depth": depth,
                    "status_code": status_code,
                    "title": title,
                    "meta_description": meta_desc,
                    "meta_keywords": meta_keywords,
                    "elements": elements,
                    "links_internal": internal_links,
                    "links_external": external_links,
                    "schema_types": parse_schema_types(html),
                    "canonical": canonical,
                    "robots": robots_meta,
                    "content_hash": content_hash,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    # Playwright-specific extras
                    "js_rendered": True,
                    "network_requests": list(dict.fromkeys(network_requests))[:30],
                    "local_storage_keys": local_storage_keys[:20],
                    "cookie_names": cookie_names[:20],
                    "tech_stack": tech_stack,
                }
                # If we hit a networkidle timeout, annotate it on the record so
                # callers can see it was a soft timeout, not a hard failure.
                if timeout_err:
                    page_record["timeout_error"] = timeout_err

                scraped_urls.append(url_norm)
                _progress({"event": "page_data", **page_record})

                _progress({"event": "page", "url": url_norm, "status": "done", "scraped": len(scraped_urls)})

                # Enqueue internal links
                if depth < max_depth:
                    for link in internal_links:
                        ln = link.rstrip("/") or link
                        if ln not in visited:
                            queue.append((ln, depth + 1))

            except PWTimeout as e:
                # A timeout outside of the navigation logic above — treat as a
                # real failure.
                err_msg = str(e)
                failed_list.append({"url": url_norm, "error": err_msg})
                _progress({"event": "page", "url": url_norm, "status": "failed", "error": err_msg})
                failed += 1
            except Exception as e:
                err_msg = str(e)
                failed_list.append({"url": url_norm, "error": err_msg})
                _progress({"event": "page", "url": url_norm, "status": "failed", "error": err_msg})
                failed += 1
            finally:
                page.close()
                time.sleep(0.5)

        browser.close()

    failed_urls = failed_list
    return {
        "base_url": base_url,
        "scraped_urls": scraped_urls,
        "failed_urls": failed_urls,
        "stats": {
            "total_pages": len(scraped_urls),
            "failed_pages": failed,
            "skipped_pages": skipped,
            "crawl_duration_s": round(time.time() - t_start, 2),
        },
    }


# ---------------------------------------------------------------------------
# Fallback: no Playwright
# ---------------------------------------------------------------------------

def crawl_fallback(base_url: str, output: str | None = None):
    print("[playwright] Playwright not installed. Installing...", file=sys.stderr)
    import subprocess
    subprocess.run(["pip", "install", "playwright", "-q"], check=False)
    subprocess.run(["playwright", "install", "chromium", "--with-deps"], check=False)
    print("[playwright] Please re-run the script after installation.", file=sys.stderr)
    result = {
        "base_url": base_url,
        "scraped_urls": [],
        "failed_urls": [],
        "error": "playwright_not_installed",
        "stats": {"total_pages": 0, "failed_pages": 0, "skipped_pages": 0, "crawl_duration_s": 0},
    }
    if output:
        with open(output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result), flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Playwright recursive website crawler")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default=None, help="Optional file path; if omitted, result is printed to stdout")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--deep", action="store_true", help="Discover all pages first, then scrape each (no limit)")
    parser.add_argument("--parallel", action="store_true", default=True, help="Run discovery and scraper threads in parallel (default: True); scraper skips URLs containing 'blog'")
    parser.add_argument("--no-parallel", action="store_false", dest="parallel", help="Disable parallel crawl")
    parser.add_argument("--no-robots", action="store_true")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    args = parser.parse_args()

    if not HAS_PLAYWRIGHT:
        crawl_fallback(args.url, args.output)
        return

    parallel = getattr(args, "parallel", False)
    deep = getattr(args, "deep", False)
    print(f"[playwright] Starting crawl: {args.url} (max={args.max_pages}, depth={args.max_depth}, deep={deep}, parallel={parallel})", file=sys.stderr)
    try:
        result = crawl_with_playwright(
            args.url, args.max_pages, args.max_depth,
            not args.no_robots, not args.no_headless,
            deep=deep,
            parallel=parallel,
        )
    except Exception as e:
        import traceback
        err_msg = f"{type(e).__name__}: {e}"
        print(f"[playwright] Error: {err_msg}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        result = {
            "base_url": args.url,
            "scraped_urls": [],
            "failed_urls": [],
            "error": "crawl_failed",
            "error_message": err_msg,
            "stats": {"total_pages": 0, "failed_pages": 0, "skipped_pages": 0, "crawl_duration_s": 0},
        }
        print(json.dumps(result), flush=True)
        sys.exit(1)

    print(f"[playwright] Done: {result['stats']['total_pages']} pages in {result['stats']['crawl_duration_s']}s", file=sys.stderr)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[playwright] Output written: {args.output}", file=sys.stderr)
    else:
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()

