"""Single-page scraping via async Playwright — returns a structured page record."""

import asyncio
import hashlib
import re
from datetime import datetime, timezone

try:
    from playwright.async_api import TimeoutError as PWTimeoutAsync
except ImportError:
    PWTimeoutAsync = Exception  # type: ignore[assignment,misc]

from html_extractor import _ELEMENTS_EVAL_JS, extract_content_elements, extract_text_from_html
from url_utils import parse_links, parse_schema_types

try:
    from ocr_helper import merge_ocr_into_elements, ocr_page_async
except ImportError:
    async def ocr_page_async(page, api_key=None): return ""  # noqa: E731
    def merge_ocr_into_elements(elements, ocr_text): return elements  # noqa: E731

import os
_OCR_API_KEY = os.getenv("GOOGLE_VISION_API_KEY", "").strip() or None


async def _scrape_single_page_async(
    context,
    url_norm: str,
    depth: int,
    base_domain: str,
    robots_parser,
    respect_robots: bool,
) -> dict | None:
    """Scrape one page fully. Returns a page record dict, or None on failure."""
    network_requests: list[str] = []

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
                    if isinstance(it, dict)
                    and str(it.get("type") or "").strip()
                    and str(it.get("content") or "").strip()
                ][:500]
        except Exception:
            elements = []
        if not elements:
            elements = extract_content_elements(html)

        ocr_text = await ocr_page_async(page, _OCR_API_KEY) if _OCR_API_KEY else ""
        if ocr_text:
            elements = merge_ocr_into_elements(elements, ocr_text)

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
    except Exception:
        return None
    finally:
        await page.close()
        await asyncio.sleep(0.3)