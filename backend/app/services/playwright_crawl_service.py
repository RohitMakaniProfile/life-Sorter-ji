"""
═══════════════════════════════════════════════════════════════
PLAYWRIGHT CRAWL SERVICE — JS-rendered website crawler
═══════════════════════════════════════════════════════════════
Replaces httpx-based crawl_website() with Playwright for full JS rendering.
Handles SPAs (React, Next.js, Vue, Angular), dynamic content, and captures
network requests (XHR/fetch = API endpoints).

Output schema is IDENTICAL to crawl_service.crawl_website() so nothing
downstream breaks (generate_crawl_summary, agent.py, playbook.py all work as-is).

Extra fields added (ignored by existing code, useful for future):
  - network_requests: list[str]  — XHR/fetch URLs (API endpoints discovered)
  - local_storage_keys: list[str]
  - cookie_names: list[str]
  - js_rendered: bool
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import structlog

from app.services import session_store

logger = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────
SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".tar", ".gz", ".exe", ".dmg",
    ".css", ".woff", ".woff2", ".ttf", ".ico",
    ".xml", ".json",
}

SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com", "pinterest.com",
    "threads.net",
}

INTERNAL_PAGE_PATTERNS = [
    (r"about|who-we-are|our-story|team", "about"),
    (r"pricing|plans|packages", "pricing"),
    (r"product|service|solution|features|what-we-do|platform", "products"),
    (r"contact|get-in-touch|reach-us|support", "contact"),
    (r"blog|news|articles|insights|resources|learn", "blog"),
    (r"case.stud|success.stor|customer.stor|testimonial|review", "case_studies"),
    (r"faq|help.center|knowledge|how.it.works", "faq"),
    (r"career|jobs|hiring|work.with|join.us", "careers"),
    (r"partner|integration|connect|ecosystem|marketplace", "partners"),
    (r"demo|trial|signup|sign-up|get.started|register", "conversion"),
    (r"portfolio|gallery|showcase|work|projects", "portfolio"),
    (r"terms|legal|privacy|refund|cancellation", "legal"),
]

TECH_PATTERNS = [
    (r"wp-content|wordpress", "WordPress"),
    (r"shopify\.com|cdn\.shopify", "Shopify"),
    (r"squarespace\.com|sqsp\.net", "Squarespace"),
    (r"wix\.com|wixstatic", "Wix"),
    (r"webflow\.com|webflow\.io", "Webflow"),
    (r"react|__next|_next/static", "React/Next.js"),
    (r"vue\.js|vuejs|__vue__", "Vue.js"),
    (r"angular|ng-version", "Angular"),
    (r"gatsby", "Gatsby"),
    (r"hubspot\.com|hs-scripts", "HubSpot"),
    (r"mailchimp\.com", "Mailchimp"),
    (r"intercom\.com|intercom-", "Intercom"),
    (r"drift\.com|drift-frame", "Drift"),
    (r"zendesk\.com|zdassets", "Zendesk"),
    (r"google-analytics|gtag|ga\.js|UA-", "Google Analytics"),
    (r"googletagmanager", "Google Tag Manager"),
    (r"hotjar\.com", "Hotjar"),
    (r"stripe\.com|stripe\.js", "Stripe"),
    (r"cloudflare", "Cloudflare"),
    (r"bootstrap|getbootstrap", "Bootstrap"),
    (r"tailwindcss|tailwind", "Tailwind CSS"),
    (r"calendly\.com", "Calendly"),
    (r"facebook\.net|fbq|fb-pixel", "Facebook Pixel"),
    # New detections Playwright enables via network/JS
    (r"segment\.com|segment\.io|analytics\.js", "Segment"),
    (r"amplitude\.com", "Amplitude"),
    (r"mixpanel\.com", "Mixpanel"),
    (r"crisp\.chat", "Crisp"),
    (r"freshdesk|freshchat", "Freshdesk"),
    (r"razorpay", "Razorpay"),
    (r"paypal\.com", "PayPal"),
    (r"supabase", "Supabase"),
    (r"firebase", "Firebase"),
]

MAX_INTERNAL_PAGES = 15
CRAWL_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# JS to extract structured DOM elements (runs inside Playwright page)
_ELEMENTS_EVAL_JS = """
() => {
  const out = [];
  const nodes = document.querySelectorAll('h1,h2,h3,p,li,img[alt],button,a[class*="btn"],a[class*="cta"]');
  for (const node of nodes) {
    if (out.length >= 500) break;
    const tag = (node.tagName || '').toLowerCase();
    let type = tag;
    let content = '';
    if (tag === 'img') {
      type = 'img_alt';
      content = (node.getAttribute('alt') || '').trim();
    } else if (tag === 'button' || (tag === 'a' && node.className.match(/btn|cta|button/i))) {
      type = 'cta';
      content = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
    } else {
      content = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
    }
    if (!content || content.length < 2) continue;
    out.push({ type, content });
  }
  return out;
}
"""

# JS to extract meta info from rendered page
_META_EVAL_JS = """
() => {
  const title = document.title || '';
  const metaDesc = document.querySelector('meta[name="description"]');
  const metaKeywords = document.querySelector('meta[name="keywords"]');
  const metaRobots = document.querySelector('meta[name="robots"]');
  const canonical = document.querySelector('link[rel="canonical"]');
  const viewport = document.querySelector('meta[name="viewport"]');
  const h1s = Array.from(document.querySelectorAll('h1')).map(el => el.innerText.trim()).filter(Boolean);
  const h2s = Array.from(document.querySelectorAll('h2')).map(el => el.innerText.trim()).filter(Boolean);
  const h3s = Array.from(document.querySelectorAll('h3')).map(el => el.innerText.trim()).filter(Boolean);

  // Internal links
  const links = Array.from(document.querySelectorAll('a[href]'))
    .map(a => a.href)
    .filter(h => h && h.startsWith('http'));

  // Social links
  const socialDomains = ['instagram.com','facebook.com','twitter.com','x.com','linkedin.com','tiktok.com','youtube.com','pinterest.com','threads.net'];
  const socialLinks = links.filter(l => {
    try { const d = new URL(l).hostname.replace('www.',''); return socialDomains.some(s => d === s || d.endsWith('.'+s)); } catch { return false; }
  });

  // Schema markup
  const schemas = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach(el => {
    try {
      const d = JSON.parse(el.textContent);
      if (Array.isArray(d)) d.forEach(i => { if (i['@type']) schemas.push(i['@type']); });
      else if (d['@type']) schemas.push(typeof d['@type'] === 'string' ? d['@type'] : JSON.stringify(d['@type']));
    } catch {}
  });

  return {
    title: title.substring(0, 200),
    meta_desc: (metaDesc ? metaDesc.getAttribute('content') || '' : '').substring(0, 500),
    meta_keywords: metaKeywords ? metaKeywords.getAttribute('content') || '' : '',
    robots_meta: metaRobots ? metaRobots.getAttribute('content') || '' : '',
    canonical: canonical ? canonical.getAttribute('href') || '' : '',
    has_viewport: !!viewport,
    h1s: h1s.slice(0, 5),
    headings: [...h2s, ...h3s].slice(0, 15),
    links: links.slice(0, 100),
    social_links: [...new Set(socialLinks)].slice(0, 10),
    schemas: schemas.slice(0, 10),
  };
}
"""


def _should_skip_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""
    return ext in SKIP_EXTENSIONS


def _detect_tech_signals(html: str, network_urls: list[str] = None) -> list[str]:
    """Detect tech stack from HTML + network requests (Playwright bonus)."""
    signals = set()
    # Check HTML
    for pattern, name in TECH_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            signals.add(name)
    # Check network requests (XHR/fetch URLs — catches lazy-loaded SDKs)
    if network_urls:
        combined = " ".join(network_urls)
        for pattern, name in TECH_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                signals.add(name)
    return list(signals)


def _classify_page_type(url: str) -> str:
    """Classify an internal page URL by pattern."""
    path = urlparse(url).path.lower()
    for pattern, page_type in INTERNAL_PAGE_PATTERNS:
        if re.search(pattern, path):
            return page_type
    return "other"


def _select_pages_to_crawl(links: list[str], base_domain: str) -> list[dict]:
    """Select most relevant internal pages (same logic as original)."""
    selected = []
    used_types = set()
    used_urls = set()

    internal_links = []
    for link in links:
        parsed = urlparse(link)
        netloc = parsed.netloc.lower()
        if (netloc == base_domain or netloc.endswith("." + base_domain)) and parsed.path != "/":
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if clean not in used_urls and not _should_skip_url(clean):
                internal_links.append(clean)
                used_urls.add(clean)

    # Phase 1: Known page types
    for link in internal_links:
        page_type = _classify_page_type(link)
        if page_type != "other" and page_type not in used_types:
            selected.append({"url": link, "type": page_type})
            used_types.add(page_type)
        if len(selected) >= MAX_INTERNAL_PAGES:
            break

    # Phase 2: Fill remaining with unmatched
    remaining = MAX_INTERNAL_PAGES - len(selected)
    selected_urls = {s["url"] for s in selected}
    if remaining > 0:
        for link in internal_links:
            if link not in selected_urls:
                selected.append({"url": link, "type": "other"})
                remaining -= 1
                if remaining <= 0:
                    break

    return selected


def _html_to_text(html: str, max_chars: int = 3000) -> str:
    """Convert HTML to plain text."""
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:max_chars]


async def crawl_website_playwright(website_url: str, session_id: str = None) -> dict:
    """
    Playwright-powered website crawler. JS-rendered, handles SPAs.

    Returns the SAME schema as crawl_service.crawl_website() for drop-in replacement:
    {
        "homepage": { "title", "meta_desc", "h1s", "headings", "nav_links" },
        "pages_crawled": [ { "url", "type", "title", "meta_desc", "headings", "key_content" } ],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [],
        "schema_markup": [],
        "seo_basics": { "has_meta", "has_viewport", "has_sitemap" },
        // Playwright extras:
        "js_rendered": true,
        "network_requests": [],
        "local_storage_keys": [],
        "cookie_names": [],
    }
    """
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    def _update_progress(phase: str, pages_found: int = 0, pages_crawled: int = 0, current_page: str = ""):
        if session_id:
            session = session_store.get_session(session_id)
            if session:
                session.crawl_progress = {
                    "phase": phase,
                    "pages_found": pages_found,
                    "pages_crawled": pages_crawled,
                    "current_page": current_page,
                }
                session_store.update_session(session)

    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    parsed_base = urlparse(website_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")

    result = {
        "homepage": {"title": "", "meta_desc": "", "h1s": [], "headings": [], "nav_links": []},
        "pages_crawled": [],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [],
        "schema_markup": [],
        "seo_basics": {"has_meta": False, "has_viewport": False, "has_sitemap": False},
        "js_rendered": True,
        "network_requests": [],
        "local_storage_keys": [],
        "cookie_names": [],
    }

    all_network_requests: list[str] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=CRAWL_USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )

            # ── Step 1: Crawl homepage (JS-rendered) ──────────────
            _update_progress("fetching_homepage", current_page=website_url)
            logger.info("Playwright crawl: starting homepage", url=website_url)

            homepage_network: list[str] = []

            def on_homepage_request(req):
                if req.resource_type in ("xhr", "fetch"):
                    homepage_network.append(req.url)

            page = await context.new_page()
            page.on("request", on_homepage_request)

            try:
                try:
                    resp = await page.goto(website_url, wait_until="networkidle", timeout=30000)
                except PWTimeout:
                    resp = None
                    logger.debug("Playwright: homepage networkidle timeout, continuing", url=website_url)

                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PWTimeout:
                    pass

                # Extract meta via JS (works for SPAs that set title/meta dynamically)
                meta = await page.evaluate(_META_EVAL_JS)
                html = await page.content()

                # Extract elements (headings, paragraphs, CTAs) via DOM traversal
                elements = await page.evaluate(_ELEMENTS_EVAL_JS)
                cta_patterns = []
                if isinstance(elements, list):
                    cta_patterns = list(set(
                        item.get("content", "")
                        for item in elements
                        if isinstance(item, dict) and item.get("type") == "cta"
                        and 2 < len(item.get("content", "")) < 50
                    ))[:10]

                # Local storage & cookies
                try:
                    local_storage_keys = await page.evaluate("Object.keys(localStorage)")
                except Exception:
                    local_storage_keys = []
                cookie_names = [c["name"] for c in await context.cookies()]

                # Has sitemap?
                has_sitemap = bool(re.search(r"sitemap\.xml", html, re.IGNORECASE))

                # Tech signals from HTML + network requests
                all_network_requests.extend(homepage_network)
                tech_signals = _detect_tech_signals(html, homepage_network)

                # Build homepage result
                nav_links = [
                    l for l in (meta.get("links") or [])
                    if urlparse(l).netloc.lower().replace("www.", "") == base_domain
                    and urlparse(l).path != "/"
                ]
                # Deduplicate and clean
                seen = set()
                clean_nav = []
                for l in nav_links:
                    parsed = urlparse(l)
                    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                    if clean not in seen and not _should_skip_url(clean):
                        seen.add(clean)
                        clean_nav.append(clean)
                nav_links = clean_nav[:30]

                result["homepage"] = {
                    "title": meta.get("title", ""),
                    "meta_desc": meta.get("meta_desc", ""),
                    "h1s": meta.get("h1s", []),
                    "headings": meta.get("headings", []),
                    "nav_links": nav_links,
                }
                result["tech_signals"] = tech_signals
                result["cta_patterns"] = cta_patterns
                result["social_links"] = meta.get("social_links", [])
                result["schema_markup"] = meta.get("schemas", [])
                result["seo_basics"] = {
                    "has_meta": bool(meta.get("title") and meta.get("meta_desc")),
                    "has_viewport": meta.get("has_viewport", False),
                    "has_sitemap": has_sitemap,
                }
                result["local_storage_keys"] = local_storage_keys[:20]
                result["cookie_names"] = cookie_names[:20]

            except Exception as e:
                logger.error("Playwright: homepage crawl failed", url=website_url, error=str(e))
                await page.close()
                await browser.close()
                return result
            finally:
                await page.close()

            # ── Step 2: Crawl internal pages in parallel batches ──
            pages_to_crawl = _select_pages_to_crawl(nav_links, base_domain)
            total_to_crawl = len(pages_to_crawl)
            _update_progress("crawling_pages", pages_found=total_to_crawl, pages_crawled=0)

            logger.info("Playwright crawl: internal pages", count=total_to_crawl, url=website_url)

            async def _crawl_one_page(ctx, page_info: dict) -> Optional[dict]:
                """Crawl a single internal page. Returns page record or None."""
                page_url = page_info["url"]
                net_reqs: list[str] = []

                def _on_req(req):
                    if req.resource_type in ("xhr", "fetch"):
                        net_reqs.append(req.url)

                pg = await ctx.new_page()
                pg.on("request", _on_req)
                try:
                    try:
                        await pg.goto(page_url, wait_until="domcontentloaded", timeout=12000)
                    except PWTimeout:
                        pass
                    # Brief wait for JS rendering (SPAs)
                    await asyncio.sleep(1.5)

                    sub_meta = await pg.evaluate(_META_EVAL_JS)
                    sub_html = await pg.content()
                    key_content = _html_to_text(sub_html, max_chars=2500)

                    # CTAs
                    sub_ctas = []
                    try:
                        sub_elements = await pg.evaluate(_ELEMENTS_EVAL_JS)
                        if isinstance(sub_elements, list):
                            sub_ctas = [
                                item.get("content", "")
                                for item in sub_elements
                                if isinstance(item, dict) and item.get("type") == "cta"
                                and 2 < len(item.get("content", "")) < 50
                            ]
                    except Exception:
                        pass

                    return {
                        "page_data": {
                            "url": page_url,
                            "type": page_info["type"],
                            "title": sub_meta.get("title", ""),
                            "meta_desc": sub_meta.get("meta_desc", ""),
                            "headings": (sub_meta.get("headings") or [])[:10],
                            "key_content": key_content,
                        },
                        "tech": _detect_tech_signals(sub_html, net_reqs),
                        "socials": sub_meta.get("social_links") or [],
                        "ctas": sub_ctas,
                        "network": net_reqs,
                    }
                except Exception as e:
                    logger.debug("Playwright: sub-page failed", url=page_url, error=str(e))
                    return None
                finally:
                    await pg.close()

            # Crawl in parallel batches of 5
            crawled_count = 0
            batch_size = 5
            for batch_start in range(0, len(pages_to_crawl), batch_size):
                batch = pages_to_crawl[batch_start:batch_start + batch_size]
                _update_progress(
                    "crawling_pages",
                    pages_found=total_to_crawl,
                    pages_crawled=crawled_count,
                    current_page=batch[0]["url"],
                )

                tasks = [_crawl_one_page(context, pi) for pi in batch]
                results_batch = await asyncio.gather(*tasks, return_exceptions=True)

                for res in results_batch:
                    if isinstance(res, dict) and res:
                        result["pages_crawled"].append(res["page_data"])
                        all_network_requests.extend(res.get("network", []))
                        result["tech_signals"] = list(set(result["tech_signals"] + res.get("tech", [])))
                        result["social_links"] = list(set(result["social_links"] + res.get("socials", [])))[:10]
                        result["cta_patterns"] = list(set(result["cta_patterns"] + res.get("ctas", [])))[:15]
                        crawled_count += 1

            # Deduplicate network requests and store
            result["network_requests"] = list(dict.fromkeys(all_network_requests))[:50]

            _update_progress("generating_summary", pages_found=total_to_crawl, pages_crawled=crawled_count)

            await browser.close()

    except Exception as e:
        logger.error("Playwright crawl failed entirely", url=website_url, error=str(e))

    logger.info(
        "Playwright crawl complete",
        url=website_url,
        pages_crawled=len(result["pages_crawled"]),
        tech_signals=len(result["tech_signals"]),
        network_requests=len(result.get("network_requests", [])),
        js_rendered=True,
    )
    return result
