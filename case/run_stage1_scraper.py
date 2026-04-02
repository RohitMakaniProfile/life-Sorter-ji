"""
═══════════════════════════════════════════════════════════════
CASE CORPUS GENERATOR — Uses the actual Stage 1 crawl_service.py
═══════════════════════════════════════════════════════════════
Imports and calls the real `crawl_website()` from
backend/app/services/crawl_service.py to generate corpus
data for each website, stored in case/<domain>/ folders.

Usage:
    cd case
    python run_stage1_scraper.py
"""

import asyncio
import json
import sys
import types
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# ── Add backend to path and stub dependencies ─────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Pre-load structlog (available in venv) - if not, stub it
try:
    import structlog  # noqa: F401
except ImportError:
    _structlog = types.ModuleType("structlog")
    class _StubLogger:
        def info(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def get_logger(self, *a, **kw): return self
        def __call__(self, *a, **kw): return self
    _structlog.get_logger = lambda *a, **kw: _StubLogger()
    sys.modules["structlog"] = _structlog

# Stub app.config so it doesn't need .env / pydantic-settings
_app_config = types.ModuleType("app.config")
class _StubSettings:
    openai_api_key_active = False
    OPENAI_MODEL_NAME = ""
    SERP_API_KEY = ""
_app_config.get_settings = lambda: _StubSettings()
sys.modules["app.config"] = _app_config

# Stub openai_service (not needed for raw crawl)
_openai_svc = types.ModuleType("app.services.openai_service")
_openai_svc._get_client = lambda: None

# Register stubs — but let the real app package load from backend/
# We need to import app/__init__.py first so it's a real package,
# then inject stubs for the specific submodules we want to skip.
import app  # noqa: E402, F401 — real package from backend/
import app.services  # noqa: E402, F401 — real sub-package

# Now override specific submodules with stubs
sys.modules["app.config"] = _app_config
sys.modules["app.services.openai_service"] = _openai_svc

# Import the real crawl_service
from app.services.crawl_service import crawl_website  # noqa: E402

# ── Websites to scrape ─────────────────────────────────────────
WEBSITES = [
    "https://www.curiousjr.com/",
    "https://endee.io/",
    "https://www.edgistify.com/",
    "https://www.pw.live/",
]

CASE_DIR = Path(__file__).resolve().parent


# ── Markdown generators (same format as before) ───────────────

def generate_format1_markdown(data: dict, url: str) -> str:
    """Landing page only markdown."""
    hp = data.get("homepage", {})
    seo = data.get("seo_basics", {})

    lines = [
        f"# Landing Page Analysis: {hp.get('title') or url}",
        f"",
        f"**URL:** {url}",
        f"**Crawled at:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Format:** Landing Page Only (Stage 1 crawl_service)",
        f"",
        f"---",
        f"",
        f"## Meta Information",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| **Title** | {hp.get('title', '—')} |",
        f"| **Meta Description** | {hp.get('meta_desc', '—')} |",
        f"| **H1 Headlines** | {', '.join(hp.get('h1s', [])) or '—'} |",
        f"| **Business Name** | {data.get('business_name', '—')} |",
        f"",
        f"## SEO Basics",
        f"",
        f"| Check | Status |",
        f"|---|---|",
        f"| Meta tags present | {'Yes' if seo.get('has_meta') else 'No'} |",
        f"| Mobile viewport | {'Yes' if seo.get('has_viewport') else 'No'} |",
        f"| Sitemap detected | {'Yes' if seo.get('has_sitemap') else 'No'} |",
        f"",
    ]

    tech = data.get("tech_signals", [])
    lines.extend([f"## Tech Stack ({len(tech)} signals)", f""])
    lines.extend([f"- {t}" for t in tech] if tech else ["- None detected"])
    lines.append("")

    ctas = data.get("cta_patterns", [])
    lines.extend([f"## CTA Patterns ({len(ctas)} found)", f""])
    lines.extend([f"- {c}" for c in ctas] if ctas else ["- None detected"])
    lines.append("")

    socials = data.get("social_links", [])
    lines.extend([f"## Social Links ({len(socials)} found)", f""])
    lines.extend([f"- {s}" for s in socials] if socials else ["- None found"])
    lines.append("")

    schemas = data.get("schema_markup", [])
    lines.extend([f"## Schema Markup ({len(schemas)} types)", f""])
    lines.extend([f"- {s}" for s in schemas] if schemas else ["- No JSON-LD schema"])
    lines.append("")

    nav = hp.get("nav_links", [])
    lines.extend([f"## Navigation Links ({len(nav)} found)", f""])
    for n in nav:
        link_url = n.get("url", n) if isinstance(n, dict) else n
        lines.append(f"- {link_url}")
    if not nav:
        lines.append("- None found")
    lines.append("")

    return "\n".join(lines)


def generate_format2_markdown(data: dict, url: str) -> str:
    """Full site crawl markdown."""
    hp = data.get("homepage", {})
    seo = data.get("seo_basics", {})
    pages = data.get("pages_crawled", [])

    lines = [
        f"# Full Site Crawl: {hp.get('title') or url}",
        f"",
        f"**URL:** {url}",
        f"**Crawled at:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Format:** Full Site (Homepage + {len(pages)} internal pages) — Stage 1 crawl_service",
        f"",
        f"---",
        f"",
        f"## Homepage Meta",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| **Title** | {hp.get('title', '—')} |",
        f"| **Meta Description** | {hp.get('meta_desc', '—')} |",
        f"| **H1 Headlines** | {', '.join(hp.get('h1s', [])) or '—'} |",
        f"| **Business Name** | {data.get('business_name', '—')} |",
        f"",
        f"## SEO Basics",
        f"",
        f"| Check | Status |",
        f"|---|---|",
        f"| Meta tags present | {'Yes' if seo.get('has_meta') else 'No'} |",
        f"| Mobile viewport | {'Yes' if seo.get('has_viewport') else 'No'} |",
        f"| Sitemap detected | {'Yes' if seo.get('has_sitemap') else 'No'} |",
        f"",
    ]

    tech = data.get("tech_signals", [])
    lines.extend([f"## Tech Stack ({len(tech)} signals)", f""])
    lines.extend([f"- {t}" for t in tech] if tech else ["- None detected"])
    lines.append("")

    ctas = data.get("cta_patterns", [])
    lines.extend([f"## CTA Patterns ({len(ctas)} found)", f""])
    lines.extend([f"- {c}" for c in ctas] if ctas else ["- None detected"])
    lines.append("")

    socials = data.get("social_links", [])
    lines.extend([f"## Social Links ({len(socials)} found)", f""])
    lines.extend([f"- {s}" for s in socials] if socials else ["- None found"])
    lines.append("")

    schemas = data.get("schema_markup", [])
    lines.extend([f"## Schema Markup ({len(schemas)} types)", f""])
    lines.extend([f"- {s}" for s in schemas] if schemas else ["- No JSON-LD schema"])
    lines.append("")

    nav = hp.get("nav_links", [])
    lines.extend([f"## Navigation Links ({len(nav)} found)", f""])
    for n in nav:
        link_url = n.get("url", n) if isinstance(n, dict) else n
        lines.append(f"- {link_url}")
    if not nav:
        lines.append("- None found")
    lines.append("")

    # Headings from homepage
    headings = hp.get("headings", [])
    if headings:
        lines.extend([f"## Homepage Headings ({len(headings)})", f""])
        for h in headings:
            lines.append(f"- {h}")
        lines.append("")

    # Internal pages
    if pages:
        lines.extend([f"---", f"", f"## Internal Pages Crawled ({len(pages)} pages)", f""])
        for i, page in enumerate(pages, 1):
            page_type = page.get("type", "unknown").title()
            lines.extend([
                f"### Page {i}: {page_type} — {page.get('title', '—')}",
                f"",
                f"**URL:** {page.get('url', '—')}",
                f"**Type:** {page.get('type', '—')}",
                f"**Meta Description:** {page.get('meta_desc', '—')}",
                f"**Headings:** {', '.join(page.get('headings', [])) or '—'}",
                f"",
                f"#### Content:",
                f"",
                f"```",
                page.get("key_content", "(No content)")[:3000],
                f"```",
                f"",
            ])
    else:
        lines.extend([f"---", f"", f"## Internal Pages", f"", f"No internal pages crawled.", f""])

    return "\n".join(lines)


# ── Main runner ────────────────────────────────────────────────

async def process_website(url: str):
    """Crawl a website using the Stage 1 crawl_service and save corpus."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    folder = CASE_DIR / domain
    folder.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Crawling: {url}")
    print(f"  Output:   case/{domain}/")
    print(f"{'='*60}")

    # Call the actual Stage 1 crawl_website function (no session_id = no session deps)
    print(f"\n  Fetching & analyzing website...")
    crawl_data = await crawl_website(url)

    pages_count = len(crawl_data.get("pages_crawled", []))
    tech_count = len(crawl_data.get("tech_signals", []))
    print(f"  Done: {pages_count} pages crawled, {tech_count} tech signals detected")

    # ── Save Format 1: Landing page data (homepage subset) ────
    landing_data = {
        "url": url,
        "homepage": crawl_data.get("homepage", {}),
        "business_name": crawl_data.get("business_name", ""),
        "tech_signals": crawl_data.get("tech_signals", []),
        "cta_patterns": crawl_data.get("cta_patterns", []),
        "social_links": crawl_data.get("social_links", []),
        "schema_markup": crawl_data.get("schema_markup", []),
        "seo_basics": crawl_data.get("seo_basics", {}),
    }

    json1_path = folder / "format1_crawl_data.json"
    json1_path.write_text(json.dumps(landing_data, indent=2, default=str), encoding="utf-8")
    print(f"  Saved: {json1_path.relative_to(CASE_DIR)}")

    md1 = generate_format1_markdown(landing_data, url)
    md1_path = folder / "format1_landing_page.md"
    md1_path.write_text(md1, encoding="utf-8")
    print(f"  Saved: {md1_path.relative_to(CASE_DIR)}")

    # ── Save Format 2: Full site crawl data ───────────────────
    full_data = {
        "url": url,
        **crawl_data,
    }

    json2_path = folder / "format2_crawl_data.json"
    json2_path.write_text(json.dumps(full_data, indent=2, default=str), encoding="utf-8")
    print(f"  Saved: {json2_path.relative_to(CASE_DIR)}")

    md2 = generate_format2_markdown(full_data, url)
    md2_path = folder / "format2_full_site.md"
    md2_path.write_text(md2, encoding="utf-8")
    print(f"  Saved: {md2_path.relative_to(CASE_DIR)}")

    print(f"\n  Done: {domain}")


async def main():
    print("=" * 60)
    print("  STAGE 1 SCRAPER — Corpus generation for case studies")
    print("  Using: backend/app/services/crawl_service.py")
    print("=" * 60)
    print(f"  Websites: {len(WEBSITES)}")
    print(f"  Output:   case/<domain>/")
    print()

    for url in WEBSITES:
        try:
            await process_website(url)
        except Exception as e:
            print(f"\n  ERROR crawling {url}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("  ALL DONE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
