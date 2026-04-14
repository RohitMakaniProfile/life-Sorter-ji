"""
Google Vision API — OCR helper for Playwright scraped pages.

Takes a Playwright page object (sync or async), screenshots it,
and returns the full extracted text via Vision API DOCUMENT_TEXT_DETECTION.

Requires: GOOGLE_VISION_API_KEY in environment (or passed directly).

Usage:
    # Sync (inside sync_playwright context)
    text = ocr_page_sync(page, api_key)

    # Async (inside async_playwright context)
    text = await ocr_page_async(page, api_key)
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
from typing import Optional

VISION_API_URL = "https://vision.googleapis.com/v1/images:annotate"
# Max image bytes to send (Vision API limit: 20MB, we cap at 4MB to keep it fast)
_MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _get_api_key(api_key: str | None = None) -> str | None:
    return api_key or os.getenv("GOOGLE_VISION_API_KEY", "").strip() or None


def _call_vision_api(image_bytes: bytes, api_key: str) -> str:
    """
    Call Google Vision DOCUMENT_TEXT_DETECTION and return extracted text.
    Returns empty string on any failure (non-blocking).
    """
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        # Truncating would corrupt the image — skip oversized screenshots
        return ""

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    body = json.dumps({
        "requests": [
            {
                "image": {"content": b64},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}],
            }
        ]
    }).encode("utf-8")

    url = f"{VISION_API_URL}?key={api_key}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"[ocr] Vision API HTTP error {e.code}: {err_body}", flush=True)
        return ""
    except Exception as e:
        print(f"[ocr] Vision API error: {e}", flush=True)
        return ""

    try:
        annotation = result["responses"][0].get("fullTextAnnotation") or {}
        return annotation.get("text", "").strip()
    except (KeyError, IndexError):
        return ""


def ocr_page_sync(page, api_key: str | None = None) -> str:
    """
    Screenshot a sync Playwright page and OCR it via Google Vision.
    Returns extracted text, or "" if Vision API key not set / call fails.
    """
    key = _get_api_key(api_key)
    if not key:
        return ""
    try:
        image_bytes: bytes = page.screenshot(full_page=True, type="png")
        text = _call_vision_api(image_bytes, key)
        print(f"[ocr] sync OCR done — {len(text)} chars extracted", flush=True)
        return text
    except Exception as e:
        print(f"[ocr] sync screenshot/OCR failed: {e}", flush=True)
        return ""


async def ocr_page_async(page, api_key: str | None = None) -> str:
    """
    Screenshot an async Playwright page and OCR it via Google Vision.
    Returns extracted text, or "" if Vision API key not set / call fails.
    """
    key = _get_api_key(api_key)
    if not key:
        return ""
    try:
        image_bytes: bytes = await page.screenshot(full_page=True, type="png")
        # Vision API call is sync (urllib) — fine to call from async context for a quick I/O op
        text = _call_vision_api(image_bytes, key)
        print(f"[ocr] async OCR done — {len(text)} chars extracted", flush=True)
        return text
    except Exception as e:
        print(f"[ocr] async screenshot/OCR failed: {e}", flush=True)
        return ""


def merge_ocr_into_elements(elements: list[dict], ocr_text: str) -> list[dict]:
    """
    Append OCR-extracted text lines as elements of type 'ocr' into the elements list.
    Deduplicates against existing element content (case-insensitive).
    """
    if not ocr_text:
        return elements

    existing = {el.get("content", "").lower().strip() for el in elements}
    new_elements = list(elements)

    for line in ocr_text.split("\n"):
        line = line.strip()
        if len(line) < 3:
            continue
        if line.lower() in existing:
            continue
        new_elements.append({"type": "ocr", "content": line})
        existing.add(line.lower())

    return new_elements
