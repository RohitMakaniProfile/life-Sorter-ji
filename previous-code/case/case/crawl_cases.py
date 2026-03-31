"""
═══════════════════════════════════════════════════════════════
CASE CRAWLER — Generate crawl data + markdown for case study websites
═══════════════════════════════════════════════════════════════
Uses the same extraction logic as backend/app/services/crawl_service.py
but runs standalone without importing the full backend (avoids heavy deps).

Format 1: Landing page only (homepage crawl data + markdown)
Format 2: Full site crawl (all discovered pages + markdown)

Usage:
    cd case
    python crawl_cases.py
"""

import asyncio
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx

# ── Constants (mirrored from crawl_service.py) ─────────────────
CRAWL_TIMEOUT = 15.0
CRAWL_USER_AGENT = "Mozilla/5.0 (compatible; IkshanBot/2.0; +https://ikshan.ai)"

INTERNAL_PAGE_PATTERNS = [
    (r"about|who-we-are|our-story|team", "about"),
    (r"pricing|plans|packages", "pricing"),
    (r"product|service|solution|features|what-we-do", "products"),
    (r"contact|get-in-touch|reach-us|support", "contact"),
    (r"blog|news|articles|insights|resources", "blog"),
]

MAX_INTERNAL_PAGES = 5

SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com", "pinterest.com",
    "threads.net",
}


# ── Extraction functions (copied from crawl_service.py) ────────

def _extract_meta(html: str) -> dict:
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
    has_viewport = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.IGNORECASE))
    has_meta = bool(title and meta_desc)
    return {"title": title[:200], "meta_desc": meta_desc[:500], "h1s": h1s[:5],
            "has_viewport": has_viewport, "has_meta": has_meta}


def _extract_nav_links(html: str, base_url: str) -> list[str]:
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    hrefs = re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\']', html, re.IGNORECASE)
    internal_links = set()
    for href in hrefs:
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc.lower() == base_domain and parsed.path != "/" and parsed.path:
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            internal_links.add(clean_url)
    return list(internal_links)[:30]


def _extract_social_links(html: str) -> list[str]:
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
    return bool(re.search(r"sitemap\.xml", html, re.IGNORECASE))


def _select_pages_to_crawl(nav_links: list[str]) -> list[dict]:
    selected = []
    used_types = set()
    for link in nav_links:
        path = urlparse(link).path.lower()
        for pattern, page_type in INTERNAL_PAGE_PATTERNS:
            if page_type not in used_types and re.search(pattern, path):
                selected.append({"url": link, "type": page_type})
                used_types.add(page_type)
                break
        if len(selected) >= MAX_INTERNAL_PAGES:
            break
    return selected


def _html_to_text(html: str, max_chars: int = 2000) -> str:
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:max_chars]


# ── Websites to crawl ─────────────────────────────────────────
WEBSITES = [
    "https://www.curiousjr.com/",
    "https://www.zomato.com/",
    "https://www.edgistify.com/",
    "https://endee.io/",
    "https://www.chimple.org/",
]

CASE_DIR = Path(__file__).resolve().parent


# ── Fetch helper ───────────────────────────────────────────────
async def fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch a single page, returns HTML or None."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  ⚠ Failed to fetch {url}: {e}")
        return None


# ── Landing page crawl (Format 1) ─────────────────────────────
async def crawl_landing_page(client: httpx.AsyncClient, url: str) -> dict:
    """Crawl ONLY the homepage / landing page."""
    result = {
        "url": url,
        "homepage": {"title": "", "meta_desc": "", "h1s": [], "nav_links": []},
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [],
        "schema_markup": [],
        "seo_basics": {"has_meta": False, "has_viewport": False, "has_sitemap": False},
        "page_text": "",
    }

    html = await fetch_page(client, url)
    if not html:
        return result

    meta = _extract_meta(html)
    nav_links = _extract_nav_links(html, url)
    social_links = _extract_social_links(html)
    schema_markup = _extract_schema_markup(html)
    tech_signals = _detect_tech_signals(html)
    cta_patterns = _extract_cta_patterns(html)
    has_sitemap = _check_sitemap(html, url)

    result["homepage"] = {
        "title": meta["title"],
        "meta_desc": meta["meta_desc"],
        "h1s": meta["h1s"],
        "nav_links": [{"url": l} for l in nav_links[:15]],
    }
    result["tech_signals"] = tech_signals
    result["cta_patterns"] = cta_patterns
    result["social_links"] = social_links
    result["schema_markup"] = schema_markup
    result["seo_basics"] = {
        "has_meta": meta["has_meta"],
        "has_viewport": meta["has_viewport"],
        "has_sitemap": has_sitemap,
    }
    result["page_text"] = _html_to_text(html, max_chars=5000)

    return result


# ── Full site crawl (Format 2) ─────────────────────────────────
async def crawl_full_site(client: httpx.AsyncClient, url: str) -> dict:
    """Crawl homepage + all discoverable internal pages."""
    result = {
        "url": url,
        "homepage": {"title": "", "meta_desc": "", "h1s": [], "nav_links": []},
        "pages_crawled": [],
        "tech_signals": [],
        "cta_patterns": [],
        "social_links": [],
        "schema_markup": [],
        "seo_basics": {"has_meta": False, "has_viewport": False, "has_sitemap": False},
        "homepage_text": "",
    }

    # Step 1: Fetch homepage
    homepage_html = await fetch_page(client, url)
    if not homepage_html:
        return result

    meta = _extract_meta(homepage_html)
    nav_links = _extract_nav_links(homepage_html, url)
    social_links = _extract_social_links(homepage_html)
    schema_markup = _extract_schema_markup(homepage_html)
    tech_signals = _detect_tech_signals(homepage_html)
    cta_patterns = _extract_cta_patterns(homepage_html)
    has_sitemap = _check_sitemap(homepage_html, url)

    result["homepage"] = {
        "title": meta["title"],
        "meta_desc": meta["meta_desc"],
        "h1s": meta["h1s"],
        "nav_links": [{"url": l} for l in nav_links[:15]],
    }
    result["tech_signals"] = tech_signals
    result["cta_patterns"] = cta_patterns
    result["social_links"] = social_links
    result["schema_markup"] = schema_markup
    result["seo_basics"] = {
        "has_meta": meta["has_meta"],
        "has_viewport": meta["has_viewport"],
        "has_sitemap": has_sitemap,
    }
    result["homepage_text"] = _html_to_text(homepage_html, max_chars=5000)

    # Step 2: Discover & crawl internal pages
    pages_to_crawl = _select_pages_to_crawl(nav_links)
    print(f"  Found {len(pages_to_crawl)} internal pages to crawl")

    if pages_to_crawl:
        tasks = [fetch_page(client, p["url"]) for p in pages_to_crawl]
        pages_html = await asyncio.gather(*tasks, return_exceptions=True)

        for page_info, html_or_err in zip(pages_to_crawl, pages_html):
            if isinstance(html_or_err, str) and html_or_err:
                key_content = _html_to_text(html_or_err, max_chars=3000)
                page_meta = _extract_meta(html_or_err)
                result["pages_crawled"].append({
                    "url": page_info["url"],
                    "type": page_info["type"],
                    "title": page_meta["title"],
                    "meta_desc": page_meta["meta_desc"],
                    "h1s": page_meta["h1s"],
                    "key_content": key_content,
                })

                # Merge tech/social from sub-pages
                result["tech_signals"] = list(
                    set(result["tech_signals"] + _detect_tech_signals(html_or_err))
                )
                sub_socials = _extract_social_links(html_or_err)
                result["social_links"] = list(
                    set(result["social_links"] + sub_socials)
                )
            else:
                print(f"  ⚠ Failed to crawl {page_info['url']}")

    return result


# ── Markdown generators ────────────────────────────────────────

def generate_format1_markdown(data: dict) -> str:
    """Generate markdown for Format 1 — landing page only."""
    hp = data["homepage"]
    seo = data["seo_basics"]
    url = data["url"]

    lines = [
        f"# 🏠 Landing Page Analysis: {hp.get('title') or url}",
        f"",
        f"**URL:** {url}",
        f"**Crawled at:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Format:** Landing Page Only",
        f"",
        f"---",
        f"",
        f"## 📋 Meta Information",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| **Title** | {hp.get('title', '—')} |",
        f"| **Meta Description** | {hp.get('meta_desc', '—')} |",
        f"| **H1 Headlines** | {', '.join(hp.get('h1s', [])) or '—'} |",
        f"",
    ]

    # SEO Basics
    lines.extend([
        f"## 🔍 SEO Basics",
        f"",
        f"| Check | Status |",
        f"|---|---|",
        f"| Meta tags present | {'✅ Yes' if seo.get('has_meta') else '❌ No'} |",
        f"| Mobile viewport | {'✅ Yes' if seo.get('has_viewport') else '❌ No'} |",
        f"| Sitemap detected | {'✅ Yes' if seo.get('has_sitemap') else '❌ No'} |",
        f"",
    ])

    # Tech Stack
    tech = data.get("tech_signals", [])
    lines.extend([
        f"## 🛠️ Tech Stack Detected ({len(tech)} signals)",
        f"",
    ])
    if tech:
        for t in tech:
            lines.append(f"- {t}")
    else:
        lines.append("- No tech signals detected")
    lines.append("")

    # CTAs
    ctas = data.get("cta_patterns", [])
    lines.extend([
        f"## 🎯 CTA Patterns ({len(ctas)} found)",
        f"",
    ])
    if ctas:
        for c in ctas:
            lines.append(f"- `{c}`")
    else:
        lines.append("- No CTAs detected")
    lines.append("")

    # Social Links
    socials = data.get("social_links", [])
    lines.extend([
        f"## 🌐 Social Links ({len(socials)} found)",
        f"",
    ])
    if socials:
        for s in socials:
            lines.append(f"- {s}")
    else:
        lines.append("- No social links found")
    lines.append("")

    # Schema Markup
    schemas = data.get("schema_markup", [])
    lines.extend([
        f"## 📊 Schema Markup ({len(schemas)} types)",
        f"",
    ])
    if schemas:
        for s in schemas:
            lines.append(f"- `{s}`")
    else:
        lines.append("- No JSON-LD schema detected")
    lines.append("")

    # Navigation Links
    nav = hp.get("nav_links", [])
    lines.extend([
        f"## 🧭 Navigation Links ({len(nav)} found)",
        f"",
    ])
    if nav:
        for n in nav:
            link_url = n.get("url", n) if isinstance(n, dict) else n
            lines.append(f"- {link_url}")
    else:
        lines.append("- No internal navigation links found")
    lines.append("")

    # Page Content (Markdown)
    page_text = data.get("page_text", "")
    lines.extend([
        f"## 📝 Landing Page Content (Extracted Text)",
        f"",
        f"```",
        page_text[:5000] if page_text else "(No content extracted)",
        f"```",
        f"",
    ])

    return "\n".join(lines)


def generate_format2_markdown(data: dict) -> str:
    """Generate markdown for Format 2 — full site crawl."""
    hp = data["homepage"]
    seo = data["seo_basics"]
    url = data["url"]
    pages = data.get("pages_crawled", [])

    lines = [
        f"# 🌐 Full Site Crawl: {hp.get('title') or url}",
        f"",
        f"**URL:** {url}",
        f"**Crawled at:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Format:** Full Site (Homepage + {len(pages)} internal pages)",
        f"",
        f"---",
        f"",
        f"## 📋 Homepage — Meta Information",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| **Title** | {hp.get('title', '—')} |",
        f"| **Meta Description** | {hp.get('meta_desc', '—')} |",
        f"| **H1 Headlines** | {', '.join(hp.get('h1s', [])) or '—'} |",
        f"",
    ]

    # SEO Basics
    lines.extend([
        f"## 🔍 SEO Basics",
        f"",
        f"| Check | Status |",
        f"|---|---|",
        f"| Meta tags present | {'✅ Yes' if seo.get('has_meta') else '❌ No'} |",
        f"| Mobile viewport | {'✅ Yes' if seo.get('has_viewport') else '❌ No'} |",
        f"| Sitemap detected | {'✅ Yes' if seo.get('has_sitemap') else '❌ No'} |",
        f"",
    ])

    # Tech Stack
    tech = data.get("tech_signals", [])
    lines.extend([
        f"## 🛠️ Tech Stack Detected ({len(tech)} signals)",
        f"",
    ])
    if tech:
        for t in tech:
            lines.append(f"- {t}")
    else:
        lines.append("- No tech signals detected")
    lines.append("")

    # CTAs
    ctas = data.get("cta_patterns", [])
    lines.extend([
        f"## 🎯 CTA Patterns ({len(ctas)} found)",
        f"",
    ])
    if ctas:
        for c in ctas:
            lines.append(f"- `{c}`")
    else:
        lines.append("- No CTAs detected")
    lines.append("")

    # Social Links
    socials = data.get("social_links", [])
    lines.extend([
        f"## 🌐 Social Links ({len(socials)} found)",
        f"",
    ])
    if socials:
        for s in socials:
            lines.append(f"- {s}")
    else:
        lines.append("- No social links found")
    lines.append("")

    # Schema Markup
    schemas = data.get("schema_markup", [])
    lines.extend([
        f"## 📊 Schema Markup ({len(schemas)} types)",
        f"",
    ])
    if schemas:
        for s in schemas:
            lines.append(f"- `{s}`")
    else:
        lines.append("- No JSON-LD schema detected")
    lines.append("")

    # Navigation Links
    nav = hp.get("nav_links", [])
    lines.extend([
        f"## 🧭 Navigation Links ({len(nav)} found)",
        f"",
    ])
    if nav:
        for n in nav:
            link_url = n.get("url", n) if isinstance(n, dict) else n
            lines.append(f"- {link_url}")
    else:
        lines.append("- No internal navigation links found")
    lines.append("")

    # Homepage Content
    hp_text = data.get("homepage_text", "")
    lines.extend([
        f"## 📝 Homepage Content (Extracted Text)",
        f"",
        f"```",
        hp_text[:5000] if hp_text else "(No content extracted)",
        f"```",
        f"",
    ])

    # ── Internal Pages ─────────────────────────────────────────
    if pages:
        lines.extend([
            f"---",
            f"",
            f"## 📄 Internal Pages Crawled ({len(pages)} pages)",
            f"",
        ])

        for i, page in enumerate(pages, 1):
            page_type = page.get("type", "unknown").title()
            lines.extend([
                f"### Page {i}: {page_type} — {page.get('title', '—')}",
                f"",
                f"**URL:** {page.get('url', '—')}",
                f"**Type:** {page.get('type', '—')}",
                f"**Meta Description:** {page.get('meta_desc', '—')}",
                f"**H1s:** {', '.join(page.get('h1s', [])) or '—'}",
                f"",
                f"#### Content:",
                f"",
                f"```",
                page.get("key_content", "(No content extracted)")[:3000],
                f"```",
                f"",
            ])
    else:
        lines.extend([
            f"---",
            f"",
            f"## 📄 Internal Pages",
            f"",
            f"No internal pages were discovered or crawled.",
            f"",
        ])

    # Raw crawl data as JSON
    lines.extend([
        f"---",
        f"",
        f"## 🗂️ Raw Crawl Data (JSON)",
        f"",
        f"<details>",
        f"<summary>Click to expand raw crawl data</summary>",
        f"",
        f"```json",
        json.dumps(data, indent=2, default=str)[:20000],
        f"```",
        f"",
        f"</details>",
        f"",
    ])

    return "\n".join(lines)


# ── Main runner ────────────────────────────────────────────────

async def process_website(url: str):
    """Process a single website — generate both Format 1 and Format 2."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    folder = CASE_DIR / domain
    folder.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"🔍 Crawling: {url}")
    print(f"   Output:   case/{domain}/")
    print(f"{'='*60}")

    async with httpx.AsyncClient(
        timeout=CRAWL_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": CRAWL_USER_AGENT},
    ) as client:

        # ── Format 1: Landing page only ───────────────────────
        print(f"\n  📄 Format 1: Landing page crawl...")
        landing_data = await crawl_landing_page(client, url)
        md1 = generate_format1_markdown(landing_data)
        f1_path = folder / "format1_landing_page.md"
        f1_path.write_text(md1, encoding="utf-8")
        print(f"  ✅ Saved: {f1_path.relative_to(CASE_DIR)}")

        # Save raw JSON too
        json1_path = folder / "format1_crawl_data.json"
        json1_path.write_text(json.dumps(landing_data, indent=2, default=str), encoding="utf-8")
        print(f"  ✅ Saved: {json1_path.relative_to(CASE_DIR)}")

        # ── Format 2: Full site crawl ─────────────────────────
        print(f"\n  🌐 Format 2: Full site crawl...")
        full_data = await crawl_full_site(client, url)
        md2 = generate_format2_markdown(full_data)
        f2_path = folder / "format2_full_site.md"
        f2_path.write_text(md2, encoding="utf-8")
        print(f"  ✅ Saved: {f2_path.relative_to(CASE_DIR)}")

        # Save raw JSON too
        json2_path = folder / "format2_crawl_data.json"
        json2_path.write_text(json.dumps(full_data, indent=2, default=str), encoding="utf-8")
        print(f"  ✅ Saved: {json2_path.relative_to(CASE_DIR)}")

    print(f"\n  ✅ Done: {domain}")


async def main():
    print("═══════════════════════════════════════════════════════════")
    print("  IKSHAN CASE CRAWLER — Generating case study crawl data  ")
    print("═══════════════════════════════════════════════════════════")
    print(f"  Websites: {len(WEBSITES)}")
    print(f"  Output:   case/<domain>/")
    print(f"  Formats:  Format 1 (landing page) + Format 2 (full site)")
    print()

    for url in WEBSITES:
        try:
            await process_website(url)
        except Exception as e:
            print(f"\n  ❌ Error crawling {url}: {e}")
            import traceback
            traceback.print_exc()

    print("\n═══════════════════════════════════════════════════════════")
    print("  ✅ ALL DONE")
    print("═══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    asyncio.run(main())
