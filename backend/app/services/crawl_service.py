"""
═══════════════════════════════════════════════════════════════
CRAWL SERVICE — Async business website crawler & analyzer
═══════════════════════════════════════════════════════════════
Crawls a user's business website in the background:
  1. Fetches homepage → extracts title, meta description, H1s, nav links
  2. Crawls up to 5 internal pages (about, pricing, products, contact, blog)
  3. Extracts tech stack signals, CTA patterns, social links, schema markup
  4. Runs lightweight SEO check (meta tags, page speed signal, mobile viewport)
  5. Generates a compressed crawl summary (5 bullet points)
  6. Stores raw + summary data in the session

Designed to run in the background while the user answers Scale Questions.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from app.config import get_settings
from app.services import session_store
from app.services.openai_service import _get_client

logger = structlog.get_logger()

# Social media domains (for url_type detection)
SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com", "pinterest.com",
    "threads.net",
}

# Google Business Profile URL patterns
GBP_DOMAINS = {
    "maps.google.com", "google.com", "maps.app.goo.gl",
    "g.page", "g.co",
}
GBP_PATH_PATTERNS = [
    r"/maps/place/",
    r"/maps\?",
    r"/maps/dir/",
    r"/maps/@",
]

# SerpAPI endpoint
SERPAPI_URL = "https://serpapi.com/search.json"

# Internal page path patterns to look for
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

# Max pages to crawl beyond homepage
MAX_INTERNAL_PAGES = 8

# HTTP client config
CRAWL_TIMEOUT = 15.0
CRAWL_USER_AGENT = "Mozilla/5.0 (compatible; IkshanBot/2.0; +https://ikshan.ai)"


def detect_url_type(url: str) -> str:
    """Detect if a URL is a social profile, Google Business Profile, or regular website."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.lower()
    query = parsed.query.lower()

    # Check for Google Business Profile URLs
    if domain in ("maps.app.goo.gl", "g.page", "g.co", "share.google"):
        return "gbp"
    if domain in ("google.com", "maps.google.com", "google.co.in"):
        for pattern in GBP_PATH_PATTERNS:
            if re.search(pattern, path + "?" + query, re.IGNORECASE):
                return "gbp"

    # Check for social profiles
    for social in SOCIAL_DOMAINS:
        if domain == social or domain.endswith("." + social):
            return "social_profile"

    return "website"


def _extract_meta(html: str) -> dict:
    """Extract title, meta description, H1s, and viewport from HTML."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    meta_desc = ""
    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not meta_match:
        meta_match = re.search(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
            html, re.IGNORECASE | re.DOTALL,
        )
    if meta_match:
        meta_desc = meta_match.group(1).strip()

    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h1s = [re.sub(r"<[^>]+>", "", h).strip() for h in h1s]

    # Extract og:site_name (most reliable company name signal)
    og_site_name = ""
    og_match = re.search(
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\'>]+)["\']',
        html, re.IGNORECASE,
    )
    if not og_match:
        og_match = re.search(
            r'<meta[^>]+content=["\']([^"\'>]+)["\'][^>]+property=["\']og:site_name["\']',
            html, re.IGNORECASE,
        )
    if og_match:
        og_site_name = og_match.group(1).strip()

    # Extract application-name meta
    app_name = ""
    app_match = re.search(
        r'<meta[^>]+name=["\']application-name["\'][^>]+content=["\']([^"\'>]+)["\']',
        html, re.IGNORECASE,
    )
    if not app_match:
        app_match = re.search(
            r'<meta[^>]+content=["\']([^"\'>]+)["\'][^>]+name=["\']application-name["\']',
            html, re.IGNORECASE,
        )
    if app_match:
        app_name = app_match.group(1).strip()

    has_viewport = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.IGNORECASE))
    has_meta = bool(title and meta_desc)

    return {
        "title": title[:200],
        "meta_desc": meta_desc[:500],
        "h1s": h1s[:5],
        "has_viewport": has_viewport,
        "has_meta": has_meta,
        "og_site_name": og_site_name[:100],
        "application_name": app_name[:100],
    }


def _extract_nav_links(html: str, base_url: str) -> list[str]:
    """Extract navigation links (internal) from HTML."""
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    # Find all href attributes
    hrefs = re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\']', html, re.IGNORECASE)
    internal_links = set()
    for href in hrefs:
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc.lower() == base_domain and parsed.path != "/" and parsed.path:
            # Clean the URL
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            internal_links.add(clean_url)

    return list(internal_links)[:30]  # Cap at 30 for processing


def _extract_social_links(html: str) -> list[str]:
    """Extract social media links from HTML."""
    hrefs = re.findall(r'<a[^>]+href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    socials = []
    for href in hrefs:
        parsed = urlparse(href)
        domain = parsed.netloc.lower().replace("www.", "")
        for social in SOCIAL_DOMAINS:
            if domain == social or domain.endswith("." + social):
                socials.append(href)
                break
    return list(set(socials))[:10]


def _extract_schema_markup(html: str) -> list[str]:
    """Extract JSON-LD schema types from HTML."""
    schemas = []
    ld_blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL,
    )
    for block in ld_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                schema_type = data.get("@type", "")
                if schema_type:
                    schemas.append(schema_type if isinstance(schema_type, str) else str(schema_type))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type"):
                        schemas.append(str(item["@type"]))
        except (json.JSONDecodeError, Exception):
            pass
    return schemas[:10]


def _detect_tech_signals(html: str) -> list[str]:
    """Detect technology stack signals from HTML source."""
    signals = []
    tech_patterns = [
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
    ]
    for pattern, name in tech_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            signals.append(name)
    return list(set(signals))


def _extract_cta_patterns(html: str) -> list[str]:
    """Extract CTA button text patterns from HTML."""
    # Look for button text and CTA-like link text
    buttons = re.findall(r"<button[^>]*>(.*?)</button>", html, re.IGNORECASE | re.DOTALL)
    cta_links = re.findall(
        r'<a[^>]+class=["\'][^"\']*(?:btn|cta|button)[^"\']*["\'][^>]*>(.*?)</a>',
        html, re.IGNORECASE | re.DOTALL,
    )
    all_ctas = buttons + cta_links
    cleaned = []
    for cta in all_ctas:
        text = re.sub(r"<[^>]+>", "", cta).strip()
        if text and len(text) < 50 and len(text) > 2:
            cleaned.append(text)
    return list(set(cleaned))[:10]


def _check_sitemap(html: str, base_url: str) -> bool:
    """Quick check if a sitemap reference exists."""
    return bool(re.search(r"sitemap\.xml", html, re.IGNORECASE))


def _select_pages_to_crawl(nav_links: list[str]) -> list[dict]:
    """Select the most relevant internal pages to crawl.
    Picks pattern-matched pages first, then fills remaining slots with
    unmatched nav links for broader site coverage."""
    selected = []
    used_types = set()
    used_urls = set()

    # Phase 1: Pick known page types by pattern
    for link in nav_links:
        path = urlparse(link).path.lower()
        for pattern, page_type in INTERNAL_PAGE_PATTERNS:
            if page_type not in used_types and re.search(pattern, path):
                selected.append({"url": link, "type": page_type})
                used_types.add(page_type)
                used_urls.add(link)
                break
        if len(selected) >= MAX_INTERNAL_PAGES:
            break

    # Phase 2: Fill remaining slots with any unmatched nav links
    remaining = MAX_INTERNAL_PAGES - len(selected)
    if remaining > 0:
        for link in nav_links:
            if link not in used_urls:
                selected.append({"url": link, "type": "other"})
                used_urls.add(link)
                remaining -= 1
                if remaining <= 0:
                    break

    return selected


def _html_to_text(html: str, max_chars: int = 3000) -> str:
    """Convert HTML to plain text, stripping scripts/styles/tags."""
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:max_chars]


def _extract_headings(html: str) -> list[str]:
    """Extract H2 and H3 headings from HTML."""
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)
    h3s = re.findall(r"<h3[^>]*>(.*?)</h3>", html, re.IGNORECASE | re.DOTALL)
    headings = [re.sub(r"<[^>]+>", "", h).strip() for h in (h2s + h3s)]
    return [h for h in headings if h and len(h) > 3][:15]


def _extract_business_name(title: str, h1s: list[str], url: str,
                           og_site_name: str = "", application_name: str = "") -> str:
    """
    Extract a clean business/company name from page metadata.

    Priority:
      1. og:site_name (most reliable — explicitly set by site owner)
      2. application-name meta tag
      3. First H1 (if short and looks like a name, ≤ 8 words)
      4. Title before common separators (|, -, –, —, :)
      5. Domain name (capitalized, subdomain-aware)
    """
    # 1. og:site_name — gold standard for company name
    if og_site_name:
        return og_site_name

    # 2. application-name meta
    if application_name:
        return application_name

    # 3. Try H1 first — often the cleanest company name
    if h1s:
        h1 = h1s[0].strip()
        if h1 and len(h1.split()) <= 8 and len(h1) <= 80:
            return h1

    # 4. Try title — split on common separators and take shortest meaningful part
    if title:
        parts = re.split(r'\s*[|–—]\s*|\s+-\s+|\s*:\s+', title)
        generic = {"home", "homepage", "welcome", "official site", "official website", "main"}
        candidates = [p.strip() for p in parts if p.strip().lower() not in generic and len(p.strip()) > 1]
        if candidates:
            best = min(candidates, key=len)
            if len(best) <= 60:
                return best

    # 5. Fallback: extract from domain (subdomain-aware)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        domain = re.sub(r"^www\.", "", domain)
        parts = domain.split(".")
        # For subdomains like app.company.com, use 'company' not 'app'
        if len(parts) >= 3:
            name_part = parts[-2]  # e.g. app.company.com → company
        else:
            name_part = parts[0]
        return name_part.capitalize()
    except Exception:
        return ""


async def _fetch_page(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Fetch a single page, returns HTML or None on failure."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.debug("Failed to fetch page", url=url, error=str(e))
        return None


async def crawl_website(website_url: str, session_id: str = None) -> dict:
    """
    Crawl a business website and extract structured data.
    If session_id is provided, updates crawl_progress in real-time.

    Returns:
        {
            "homepage": { "title", "meta_desc", "h1s", "headings", "nav_links" },
            "pages_crawled": [ { "url", "type", "title", "meta_desc", "headings", "key_content" } ],
            "tech_signals": [],
            "cta_patterns": [],
            "social_links": [],
            "schema_markup": [],
            "seo_basics": { "has_meta", "has_viewport", "has_sitemap" }
        }
    """
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

    result = {
        "homepage": {"title": "", "meta_desc": "", "h1s": [], "headings": [], "nav_links": []},
        "pages_crawled": [],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [],
        "schema_markup": [],
        "seo_basics": {"has_meta": False, "has_viewport": False, "has_sitemap": False},
    }

    async with httpx.AsyncClient(
        timeout=CRAWL_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": CRAWL_USER_AGENT},
    ) as client:
        # ── Step 1: Fetch homepage ─────────────────────────────
        _update_progress("fetching_homepage", current_page=website_url)
        homepage_html = await _fetch_page(client, website_url)
        if not homepage_html:
            logger.warning("Could not fetch homepage", url=website_url)
            return result

        # Extract homepage metadata
        meta = _extract_meta(homepage_html)
        nav_links = _extract_nav_links(homepage_html, website_url)
        social_links = _extract_social_links(homepage_html)
        schema_markup = _extract_schema_markup(homepage_html)
        tech_signals = _detect_tech_signals(homepage_html)
        cta_patterns = _extract_cta_patterns(homepage_html)
        has_sitemap = _check_sitemap(homepage_html, website_url)
        homepage_headings = _extract_headings(homepage_html)

        result["homepage"] = {
            "title": meta["title"],
            "meta_desc": meta["meta_desc"],
            "h1s": meta["h1s"],
            "headings": homepage_headings,
            "nav_links": nav_links[:15],
        }
        result["business_name"] = _extract_business_name(
            meta["title"], meta["h1s"], website_url,
            og_site_name=meta.get("og_site_name", ""),
            application_name=meta.get("application_name", ""),
        )
        result["tech_signals"] = tech_signals
        result["cta_patterns"] = cta_patterns
        result["social_links"] = social_links
        result["schema_markup"] = schema_markup
        result["seo_basics"] = {
            "has_meta": meta["has_meta"],
            "has_viewport": meta["has_viewport"],
            "has_sitemap": has_sitemap,
        }

        # ── Step 2: Crawl internal pages ───────────────────────
        pages_to_crawl = _select_pages_to_crawl(nav_links)
        total_to_crawl = len(pages_to_crawl)
        crawled_count = 0
        _update_progress("crawling_pages", pages_found=total_to_crawl, pages_crawled=0)

        if pages_to_crawl:
            # Crawl in batches of 5 for progress visibility
            batch_size = 5
            for batch_start in range(0, len(pages_to_crawl), batch_size):
                batch = pages_to_crawl[batch_start:batch_start + batch_size]
                _update_progress(
                    "crawling_pages",
                    pages_found=total_to_crawl,
                    pages_crawled=crawled_count,
                    current_page=batch[0]["url"],
                )

                tasks = [_fetch_page(client, p["url"]) for p in batch]
                pages_html = await asyncio.gather(*tasks, return_exceptions=True)

                for page_info, html_or_err in zip(batch, pages_html):
                    crawled_count += 1
                    if isinstance(html_or_err, str) and html_or_err:
                        page_meta = _extract_meta(html_or_err)
                        key_content = _html_to_text(html_or_err, max_chars=2500)
                        page_headings = _extract_headings(html_or_err)
                        page_ctas = _extract_cta_patterns(html_or_err)

                        result["pages_crawled"].append({
                            "url": page_info["url"],
                            "type": page_info["type"],
                            "title": page_meta["title"],
                            "meta_desc": page_meta["meta_desc"],
                            "headings": page_headings[:10],
                            "key_content": key_content,
                        })

                        # Merge tech/social/CTAs from sub-pages
                        result["tech_signals"] = list(
                            set(result["tech_signals"] + _detect_tech_signals(html_or_err))
                        )
                        sub_socials = _extract_social_links(html_or_err)
                        result["social_links"] = list(
                            set(result["social_links"] + sub_socials)
                        )
                        result["cta_patterns"] = list(
                            set(result["cta_patterns"] + page_ctas)
                        )[:15]

                _update_progress(
                    "crawling_pages",
                    pages_found=total_to_crawl,
                    pages_crawled=crawled_count,
                )

        _update_progress("generating_summary", pages_found=total_to_crawl, pages_crawled=crawled_count)

    logger.info(
        "Website crawl complete",
        url=website_url,
        pages_crawled=len(result["pages_crawled"]),
        tech_signals=len(result["tech_signals"]),
    )
    return result


async def generate_crawl_summary(crawl_raw: dict, website_url: str) -> dict:
    """
    Generate a compressed 5-bullet summary from raw crawl data using GPT.

    Returns:
        {
            "points": ["bullet 1", "bullet 2", ...],
            "crawl_status": "complete",
            "completed_at": "ISO-timestamp"
        }
    """
    settings = get_settings()
    if not settings.openai_api_key_active:
        # Fallback: generate basic summary without GPT
        return _generate_fallback_summary(crawl_raw)

    client = _get_client()

    # Build context from raw crawl
    context_parts = []
    hp = crawl_raw.get("homepage", {})
    if hp.get("title"):
        context_parts.append(f"Homepage Title: {hp['title']}")
    if hp.get("meta_desc"):
        context_parts.append(f"Meta Description: {hp['meta_desc']}")
    if hp.get("h1s"):
        context_parts.append(f"H1 Headlines: {', '.join(hp['h1s'][:3])}")

    tech = crawl_raw.get("tech_signals", [])
    if tech:
        context_parts.append(f"Tech Stack: {', '.join(tech[:8])}")

    ctas = crawl_raw.get("cta_patterns", [])
    if ctas:
        context_parts.append(f"CTAs Found: {', '.join(ctas[:5])}")

    socials = crawl_raw.get("social_links", [])
    if socials:
        context_parts.append(f"Social Profiles: {len(socials)} found")

    seo = crawl_raw.get("seo_basics", {})
    seo_notes = []
    if not seo.get("has_meta"):
        seo_notes.append("Missing meta tags")
    if not seo.get("has_viewport"):
        seo_notes.append("No mobile viewport")
    if not seo.get("has_sitemap"):
        seo_notes.append("No sitemap detected")
    if seo_notes:
        context_parts.append(f"SEO Issues: {', '.join(seo_notes)}")

    pages = crawl_raw.get("pages_crawled", [])
    if pages:
        context_parts.append(f"Pages Crawled: {len(pages)} ({', '.join(p.get('type', '') for p in pages)})")
        for p in pages[:3]:
            content_preview = p.get("key_content", "")[:300]
            if content_preview:
                context_parts.append(f"  [{p.get('type', 'page')}]: {content_preview}")

    crawl_context = "\n".join(context_parts)

    system_prompt = (
        "You are a concise business analyst. Given website crawl data, "
        "produce exactly 5 bullet points (5-10 words each) summarizing "
        "the business: what they do, who they target, their tech sophistication, "
        "key strengths, and one notable gap or opportunity.\n\n"
        "Return ONLY a JSON object: {\"points\": [\"...\", \"...\", \"...\", \"...\", \"...\"]}"
    )
    user_message = f"Website: {website_url}\n\nCrawl Data:\n{crawl_context}"

    try:
        import time as _time
        _t0 = _time.time()

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=300,
            response_format={"type": "json_object"},
        )

        _latency = int((_time.time() - _t0) * 1000)
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        points = parsed.get("points", [])[:5]

        usage = response.usage
        token_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        } if usage else {}

        return {
            "points": points,
            "crawl_status": "complete",
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "_meta": {
                "service": "openai",
                "model": settings.OPENAI_MODEL_NAME,
                "system_prompt": system_prompt,
                "user_message": user_message,
                "temperature": 0.3,
                "max_tokens": 300,
                "raw_response": raw,
                "latency_ms": _latency,
                "token_usage": token_usage,
            },
        }

    except Exception as e:
        logger.error("GPT crawl summary generation failed", error=str(e))
        return _generate_fallback_summary(crawl_raw)


def _generate_fallback_summary(crawl_raw: dict) -> dict:
    """Generate a basic summary without GPT."""
    points = []
    hp = crawl_raw.get("homepage", {})
    if hp.get("title"):
        points.append(f"Business: {hp['title'][:50]}")
    if hp.get("meta_desc"):
        points.append(hp["meta_desc"][:60])

    tech = crawl_raw.get("tech_signals", [])
    if tech:
        points.append(f"Uses: {', '.join(tech[:3])}")

    pages = crawl_raw.get("pages_crawled", [])
    if pages:
        points.append(f"{len(pages)} key pages identified")

    seo = crawl_raw.get("seo_basics", {})
    issues = []
    if not seo.get("has_meta"):
        issues.append("meta tags")
    if not seo.get("has_viewport"):
        issues.append("mobile viewport")
    if issues:
        points.append(f"Missing: {', '.join(issues)}")

    if not points:
        points = ["Website data collected for analysis"]

    return {
        "points": points[:5],
        "crawl_status": "complete",
        "completed_at": datetime.utcnow().isoformat() + "Z",
    }


async def run_background_crawl(session_id: str, website_url: str):
    """
    Run the full crawl pipeline in the background.
    Called as an asyncio task — does not block the API response.

    Steps:
    1. Set crawl_status to "in_progress"
    2. Crawl the website (or social profile)
    3. Generate summary
    4. Store results in session
    5. Set crawl_status to "complete" (or "failed")
    """
    try:
        # Mark crawl as in progress
        session_store.set_crawl_status(session_id, "in_progress")
        logger.info("Background crawl started", session_id=session_id, url=website_url)

        # Determine URL type and run appropriate crawl
        url_type = detect_url_type(website_url)
        if url_type == "gbp":
            crawl_raw = await crawl_gbp(website_url, session_id=session_id)
        elif url_type == "social_profile":
            crawl_raw = await crawl_social_profile(website_url)
        else:
            crawl_raw = await crawl_website(website_url, session_id=session_id)

        # Generate compressed summary (with _meta for context pool)
        if url_type == "gbp":
            crawl_summary = await generate_gbp_summary(crawl_raw, website_url)
        else:
            crawl_summary = await generate_crawl_summary(crawl_raw, website_url)

        # Log crawl summary LLM call to context pool
        if "_meta" in crawl_summary:
            meta = crawl_summary.pop("_meta")
            session_store.add_llm_call_log(
                session_id=session_id,
                service=meta.get("service", "openai"),
                model=meta.get("model", "gpt-4o-mini"),
                purpose="crawl_summary",
                system_prompt=meta.get("system_prompt", ""),
                user_message=meta.get("user_message", ""),
                temperature=meta.get("temperature", 0.3),
                max_tokens=meta.get("max_tokens", 300),
                raw_response=meta.get("raw_response", ""),
                latency_ms=meta.get("latency_ms", 0),
                token_usage=meta.get("token_usage", {}),
            )

        # Store in session
        session_store.set_crawl_data(session_id, crawl_raw, crawl_summary)

        # Store GBP-specific data if available
        if url_type == "gbp" and crawl_raw.get("gbp_data"):
            session = session_store.get_session(session_id)
            if session:
                session.gbp_data = crawl_raw["gbp_data"]
                session_store.update_session(session)

        # Mark progress complete
        session = session_store.get_session(session_id)
        if session:
            session.crawl_progress = {
                "phase": "complete",
                "pages_found": len(crawl_raw.get("pages_crawled", [])),
                "pages_crawled": len(crawl_raw.get("pages_crawled", [])),
                "current_page": "",
            }
            session_store.update_session(session)

        logger.info(
            "Background crawl complete",
            session_id=session_id,
            url=website_url,
            url_type=url_type,
            pages=len(crawl_raw.get("pages_crawled", [])),
            tech_signals=len(crawl_raw.get("tech_signals", [])),
        )

    except Exception as e:
        logger.error(
            "Background crawl failed",
            session_id=session_id,
            url=website_url,
            error=str(e),
        )
        session_store.set_crawl_status(session_id, "failed")


# ═══════════════════════════════════════════════════════════════
# GOOGLE BUSINESS PROFILE SCRAPING (via SerpAPI)
# ═══════════════════════════════════════════════════════════════


def _extract_place_name_from_url(url: str) -> str:
    """Extract a business/place name from a Google Maps URL for search."""
    parsed = urlparse(url)
    path = parsed.path

    # /maps/place/Business+Name/...
    place_match = re.search(r"/maps/place/([^/]+)", path)
    if place_match:
        name = place_match.group(1)
        # URL-decode and clean
        from urllib.parse import unquote
        name = unquote(name).replace("+", " ")
        return name

    # /maps?q=Business+Name
    q_match = re.search(r"[?&]q=([^&]+)", parsed.query)
    if q_match:
        from urllib.parse import unquote
        return unquote(q_match.group(1)).replace("+", " ")

    return ""


async def crawl_gbp(url: str, session_id: str = None) -> dict:
    """
    Scrape Google Business Profile data using SerpAPI.

    Extracts:
    - Business name, address, phone, website, category
    - Rating, total reviews
    - Operating hours
    - Top reviews (text, rating, date)
    - Photos count
    - Service options (dine-in, takeaway, delivery, etc.)

    Returns a dict compatible with crawl_raw structure,
    plus a 'gbp_data' key with structured GBP-specific data.
    """
    settings = get_settings()
    api_key = settings.SERP_API_KEY

    if not api_key:
        logger.warning("SerpAPI key not configured — GBP scraping unavailable")
        return _gbp_fallback(url)

    # Extract place name from URL
    place_name = _extract_place_name_from_url(url)
    if not place_name:
        # Fall back to using the full URL as the query
        place_name = url

    logger.info("GBP scrape: searching for place", place_name=place_name, url=url)

    gbp_data = {
        "business_name": "",
        "address": "",
        "phone": "",
        "website": "",
        "category": "",
        "rating": None,
        "total_reviews": 0,
        "price_level": "",
        "hours": [],
        "service_options": [],
        "reviews": [],
        "photos_count": 0,
        "place_id": "",
        "description": "",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Step 1: Search for the place via Google Maps
            search_params = {
                "engine": "google_maps",
                "q": place_name,
                "api_key": api_key,
                "type": "search",
                "hl": "en",
            }

            resp = await client.get(SERPAPI_URL, params=search_params)
            resp.raise_for_status()
            search_data = resp.json()

            # Find the place from local results
            local_results = search_data.get("local_results", [])
            if not local_results:
                # Try place_results for direct match
                place_info = search_data.get("place_results", {})
                if not place_info:
                    logger.warning("GBP: no results found", query=place_name)
                    return _gbp_fallback(url)
            else:
                place_info = local_results[0]

            # Extract basic info
            gbp_data["business_name"] = place_info.get("title", "")
            gbp_data["address"] = place_info.get("address", "")
            gbp_data["phone"] = place_info.get("phone", "")
            gbp_data["website"] = place_info.get("website", "")
            gbp_data["category"] = place_info.get("type", "") or place_info.get("category", "")
            gbp_data["rating"] = place_info.get("rating")
            gbp_data["total_reviews"] = place_info.get("reviews", 0)
            gbp_data["price_level"] = place_info.get("price", "")
            gbp_data["description"] = place_info.get("description", "")
            gbp_data["photos_count"] = place_info.get("photos_count", 0) or len(place_info.get("photos", []))
            gbp_data["place_id"] = place_info.get("place_id", "") or place_info.get("data_id", "")

            # Hours
            hours = place_info.get("operating_hours", {}) or place_info.get("hours", [])
            if isinstance(hours, dict):
                gbp_data["hours"] = [
                    f"{day}: {time}" for day, time in hours.items()
                ]
            elif isinstance(hours, list):
                gbp_data["hours"] = hours[:7]

            # Service options
            service_opts = place_info.get("service_options", {})
            if isinstance(service_opts, dict):
                gbp_data["service_options"] = [
                    key for key, val in service_opts.items() if val
                ]

            # Step 2: Fetch reviews if we have a place_id/data_id
            data_id = place_info.get("data_id", "") or gbp_data["place_id"]
            if data_id:
                try:
                    reviews_params = {
                        "engine": "google_maps_reviews",
                        "data_id": data_id,
                        "api_key": api_key,
                        "hl": "en",
                        "sort_by": "qualityScore",  # Most relevant reviews
                    }
                    reviews_resp = await client.get(SERPAPI_URL, params=reviews_params)
                    reviews_resp.raise_for_status()
                    reviews_data = reviews_resp.json()

                    raw_reviews = reviews_data.get("reviews", [])[:10]
                    gbp_data["reviews"] = [
                        {
                            "rating": r.get("rating", 0),
                            "text": (r.get("snippet", "") or r.get("text", ""))[:500],
                            "date": r.get("date", ""),
                            "user": r.get("user", {}).get("name", "") if isinstance(r.get("user"), dict) else "",
                            "likes": r.get("likes", 0),
                        }
                        for r in raw_reviews
                        if r.get("snippet") or r.get("text")
                    ]

                    logger.info(
                        "GBP: reviews fetched",
                        count=len(gbp_data["reviews"]),
                        place=gbp_data["business_name"],
                    )
                except Exception as e:
                    logger.warning("GBP: reviews fetch failed", error=str(e))

    except httpx.HTTPStatusError as e:
        logger.error("GBP SerpAPI HTTP error", status=e.response.status_code, body=e.response.text[:300])
        return _gbp_fallback(url)
    except Exception as e:
        logger.error("GBP scrape failed", error=str(e))
        return _gbp_fallback(url)

    logger.info(
        "GBP scrape complete",
        business=gbp_data["business_name"],
        rating=gbp_data["rating"],
        reviews=gbp_data["total_reviews"],
        fetched_reviews=len(gbp_data["reviews"]),
    )

    # Build crawl_raw-compatible structure with GBP data
    return {
        "homepage": {
            "title": gbp_data["business_name"],
            "meta_desc": gbp_data["description"] or f"{gbp_data['category']} — {gbp_data['address']}",
            "h1s": [gbp_data["business_name"]],
            "headings": [],
            "nav_links": [],
        },
        "pages_crawled": [],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [gbp_data["website"]] if gbp_data["website"] else [],
        "schema_markup": ["LocalBusiness"],
        "seo_basics": {"has_meta": True, "has_viewport": True, "has_sitemap": False},
        "gbp_data": gbp_data,
    }


def _gbp_fallback(url: str) -> dict:
    """Minimal fallback when GBP scraping fails."""
    return {
        "homepage": {"title": "", "meta_desc": "", "h1s": [], "headings": [], "nav_links": []},
        "pages_crawled": [],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [],
        "schema_markup": [],
        "seo_basics": {"has_meta": False, "has_viewport": True, "has_sitemap": False},
        "gbp_data": {},
    }


async def generate_gbp_summary(crawl_raw: dict, url: str) -> dict:
    """
    Generate a compressed summary from GBP data using GPT.
    Falls back to a rule-based summary if GPT is unavailable.
    """
    gbp = crawl_raw.get("gbp_data", {})
    if not gbp or not gbp.get("business_name"):
        return _generate_fallback_summary(crawl_raw)

    settings = get_settings()
    if not settings.openai_api_key_active:
        return _generate_gbp_fallback_summary(gbp)

    client = _get_client()

    # Build rich context from GBP data
    context_parts = []
    context_parts.append(f"Business Name: {gbp['business_name']}")
    if gbp.get("category"):
        context_parts.append(f"Category: {gbp['category']}")
    if gbp.get("address"):
        context_parts.append(f"Address: {gbp['address']}")
    if gbp.get("rating"):
        context_parts.append(f"Rating: {gbp['rating']}/5 ({gbp.get('total_reviews', 0)} reviews)")
    if gbp.get("price_level"):
        context_parts.append(f"Price Level: {gbp['price_level']}")
    if gbp.get("service_options"):
        context_parts.append(f"Services: {', '.join(gbp['service_options'])}")
    if gbp.get("hours"):
        context_parts.append(f"Hours: {'; '.join(gbp['hours'][:3])}")
    if gbp.get("website"):
        context_parts.append(f"Website: {gbp['website']}")

    # Include review highlights
    reviews = gbp.get("reviews", [])
    if reviews:
        context_parts.append(f"\nTop {len(reviews)} Reviews:")
        for i, r in enumerate(reviews[:5], 1):
            context_parts.append(f"  {i}. [{r.get('rating', '?')}★] {r['text'][:200]}")

    gbp_context = "\n".join(context_parts)

    system_prompt = (
        "You are a concise business analyst. Given Google Business Profile data, "
        "produce exactly 5 bullet points (5-10 words each) summarizing: "
        "what the business does, their reputation (rating + review themes), "
        "their local presence strength, one key positive from reviews, "
        "and one gap or opportunity spotted.\n\n"
        'Return ONLY a JSON object: {"points": ["...", "...", "...", "...", "..."]}'
    )
    user_message = f"Google Business Profile: {url}\n\n{gbp_context}"

    try:
        import time as _time
        _t0 = _time.time()

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=300,
            response_format={"type": "json_object"},
        )

        _latency = int((_time.time() - _t0) * 1000)
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        points = parsed.get("points", [])[:5]

        usage = response.usage
        token_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        } if usage else {}

        return {
            "points": points,
            "crawl_status": "complete",
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "_meta": {
                "service": "openai",
                "model": settings.OPENAI_MODEL_NAME,
                "system_prompt": system_prompt,
                "user_message": user_message,
                "temperature": 0.3,
                "max_tokens": 300,
                "raw_response": raw,
                "latency_ms": _latency,
                "token_usage": token_usage,
            },
        }

    except Exception as e:
        logger.error("GPT GBP summary failed", error=str(e))
        return _generate_gbp_fallback_summary(gbp)


def _generate_gbp_fallback_summary(gbp: dict) -> dict:
    """Generate a basic GBP summary without GPT."""
    points = []
    if gbp.get("business_name"):
        cat = gbp.get("category", "")
        points.append(f"{gbp['business_name']}{' — ' + cat if cat else ''}")
    if gbp.get("rating"):
        points.append(f"Rated {gbp['rating']}/5 from {gbp.get('total_reviews', 0)} reviews")
    if gbp.get("address"):
        points.append(f"Located: {gbp['address'][:60]}")
    if gbp.get("reviews"):
        avg_sentiment = sum(r.get("rating", 0) for r in gbp["reviews"]) / len(gbp["reviews"])
        points.append(f"Review avg: {avg_sentiment:.1f}★ from sampled reviews")
    if gbp.get("service_options"):
        points.append(f"Offers: {', '.join(gbp['service_options'][:4])}")

    if not points:
        points = ["Google Business Profile data collected"]

    return {
        "points": points[:5],
        "crawl_status": "complete",
        "completed_at": datetime.utcnow().isoformat() + "Z",
    }


async def crawl_social_profile(website_url: str) -> dict:
    """
    Lightweight crawl for social media profile URLs.
    Extracts bio, profile info from the page.
    """
    result = {
        "homepage": {"title": "", "meta_desc": "", "h1s": [], "nav_links": []},
        "pages_crawled": [],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [website_url],
        "schema_markup": [],
        "seo_basics": {"has_meta": False, "has_viewport": True, "has_sitemap": False},
    }

    async with httpx.AsyncClient(
        timeout=CRAWL_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": CRAWL_USER_AGENT},
    ) as client:
        html = await _fetch_page(client, website_url)
        if html:
            meta = _extract_meta(html)
            result["homepage"] = {
                "title": meta["title"],
                "meta_desc": meta["meta_desc"],
                "h1s": meta["h1s"],
                "nav_links": [],
            }
            result["schema_markup"] = _extract_schema_markup(html)

    return result
