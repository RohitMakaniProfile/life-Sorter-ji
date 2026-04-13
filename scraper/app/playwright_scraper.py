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


_GMAPS_PLACE_EXTRACT_JS = r"""
() => {
  const r = {};

  // ─── Detect the place card panel ─────────────────────────────────────────
  // Google Maps has two layouts:
  //   (a) Pure place URL  → [role="main"] IS the place panel
  //   (b) Search+place hybrid → place card popup lives alongside search results
  //       In this layout the search-results list also lives inside [role="main"].
  // We detect by finding h1.DUwDvf (the business name heading — only in place
  // cards, never in the search-results list) and walking UP to the nearest
  // ancestor that also contains the action buttons / tab bar.
  let panel = null;
  {
    const nameEl = document.querySelector('h1.DUwDvf');
    if (nameEl) {
      let el = nameEl.parentElement;
      while (el && el !== document.body) {
        // A container that holds the place-card tabs or the address button
        // is the place panel boundary.
        if (el.querySelector('button[role="tab"]') ||
            el.querySelector('button[data-item-id="address"]')) {
          panel = el;
          break;
        }
        el = el.parentElement;
      }
      if (!panel) {
        // No tab container found walking up — settle for the closest
        // [role="main"] ancestor that contains nameEl.
        let up = nameEl.parentElement;
        while (up && up !== document.body) {
          if (up.getAttribute('role') === 'main') { panel = up; break; }
          up = up.parentElement;
        }
      }
    }
    if (!panel) {
      const main = document.querySelector('[role="main"]');
      if (main && (main.querySelector('h1.DUwDvf') ||
                   main.querySelector('button[data-item-id="address"]') ||
                   main.querySelector('button[role="tab"]'))) {
        panel = main;
      }
    }
    if (!panel) panel = document.querySelector('[role="main"]') || document.body;

    // Extra fallback: Reviews-tab-pre-active layout (!9m1!1b1 URLs).
    // h1.DUwDvf is hidden when the Reviews tab is already open on load.
    // Detect by checking if a Reviews tab is aria-selected, then walk up
    // from the tab bar to the container holding the review cards.
    if (panel === document.body || panel === document.querySelector('[role="main"]')) {
      const activeReviewTab = document.querySelector(
        'button[role="tab"][aria-selected="true"][aria-label*="Review" i]'
      );
      if (activeReviewTab) {
        let el = activeReviewTab.parentElement;
        while (el && el !== document.body) {
          if (el.querySelector('[data-review-id]') ||
              el.querySelector('button[data-item-id]')) {
            panel = el;
            break;
          }
          el = el.parentElement;
        }
      }
    }
  }

  // Scoped query helpers — always search within the place card panel.
  const $  = (sel) => { try { return panel.querySelector(sel); }   catch(e) { return null; } };
  const $$ = (sel) => { try { return Array.from(panel.querySelectorAll(sel)); } catch(e) { return []; } };

  // ─── Business name ───────────────────────────────────────────────────────
  // Query document-wide for h1.DUwDvf — it is place-card-specific and will
  // never match the "Results" heading of the search-results list.
  {
    const nameEl = document.querySelector('h1.DUwDvf');
    r.name = nameEl ? nameEl.innerText.trim() : '';
    if (!r.name) { const h = $('h1'); if (h) r.name = h.innerText.trim(); }
    if (!r.name) r.name = (panel.getAttribute('aria-label') || '').trim();
    // Last resort: extract from any tab's aria-label
    // e.g. "Reviews for Shivam Dental Clinic" → "Shivam Dental Clinic"
    if (!r.name) {
      const anyTab = document.querySelector('button[role="tab"][aria-label]');
      if (anyTab) {
        const al = anyTab.getAttribute('aria-label') || '';
        const m  = al.match(/(?:Overview|Reviews|About) (?:for|of) (.+)/i);
        if (m) r.name = m[1].trim();
      }
    }
  }

  // ─── Rating & review count ───────────────────────────────────────────────
  // Strategy order matters: F7nice is ALWAYS inside the place card panel
  // (not in the search-result list), so it is tried first.  ZkP5Je elements
  // live in the search-result list cards, so scoping to panel prevents
  // picking up a neighbour business — but only as a secondary fallback.
  r.rating      = '';
  r.reviewCount = '';

  // Strategy A: F7nice — the dedicated rating row inside the place card.
  // <div class="F7nice">
  //   <span><span aria-hidden="true">5.0</span>…stars…</span>
  //   <span><span role="img" aria-label="14 reviews">(14)</span></span>
  // </div>
  {
    const ratingRow = $('div.F7nice');
    if (ratingRow) {
      const numSpan = ratingRow.querySelector('span[aria-hidden="true"]');
      if (numSpan) r.rating = numSpan.innerText.trim();

      for (const s of ratingRow.querySelectorAll('span, a')) {
        const al = s.getAttribute('aria-label') || '';
        if (/review/i.test(al)) { r.reviewCount = al.replace(/[^0-9]/g, ''); break; }
        const txt = (s.innerText || '').trim();
        if (/\(\d/.test(txt))   { r.reviewCount = txt.replace(/[^0-9]/g, ''); break; }
      }
      // Walk up two levels — sometimes count is a sibling/cousin of F7nice.
      if (!r.reviewCount) {
        const containers = [ratingRow.parentElement,
                            ratingRow.parentElement && ratingRow.parentElement.parentElement];
        for (const c of containers) {
          if (!c) continue;
          for (const el of c.querySelectorAll('span, a, button')) {
            const al = el.getAttribute('aria-label') || '';
            if (/\d+\s*review/i.test(al)) { r.reviewCount = al.replace(/[^0-9]/g, ''); break; }
            const txt = (el.innerText || '').trim();
            if (/^\(?\d{1,6}\)?$/.test(txt) && parseInt(txt.replace(/[^0-9]/g, '')) > 0) {
              r.reviewCount = txt.replace(/[^0-9]/g, ''); break;
            }
          }
          if (r.reviewCount) break;
        }
      }
    }
  }

  // Strategy B: ZkP5Je — combined "X.X stars N Reviews" aria-label.
  // Only used when panel-scoped (prevents neighbour-business contamination).
  if (!r.rating || !r.reviewCount) {
    const zkEl = $('span.ZkP5Je[aria-label]');
    if (zkEl) {
      const al = zkEl.getAttribute('aria-label') || '';
      const mRat = al.match(/([\d.]+)\s*star/i);
      const mRev = al.match(/([\d,]+)\s*review/i);
      if (!r.rating      && mRat) r.rating      = mRat[1];
      if (!r.reviewCount && mRev) r.reviewCount = mRev[1].replace(/,/g, '');
    }
  }

  // Strategy C: [role="img"] with "X.X stars" aria-label within the panel.
  if (!r.rating) {
    const starEl = $('[role="img"][aria-label*="star" i]');
    if (starEl) {
      const m = (starEl.getAttribute('aria-label') || '').match(/([\d.]+)/);
      if (m) r.rating = m[1];
    }
  }

  // Strategy D: Reviews tab button aria-label — e.g. "Reviews (14)".
  if (!r.reviewCount) {
    const reviewsTab = $('button[role="tab"][aria-label*="Review" i]');
    if (reviewsTab) {
      const al = reviewsTab.getAttribute('aria-label') || '';
      const m  = al.match(/([\d,]+)/);
      if (m) r.reviewCount = m[1].replace(/,/g, '');
      if (!r.reviewCount) {
        const m2 = (reviewsTab.innerText || '').match(/([\d,]+)/);
        if (m2) r.reviewCount = m2[1].replace(/,/g, '');
      }
    }
  }

  // Strategy E: broad panel scan for "N reviews" text / aria-label patterns.
  if (!r.reviewCount) {
    for (const el of $$('span, a, button')) {
      const al = el.getAttribute('aria-label') || '';
      if (/([\d,]+)\s*review/i.test(al)) {
        const m = al.match(/([\d,]+)/);
        if (m) { r.reviewCount = m[1].replace(/,/g, ''); break; }
      }
      const t = (el.innerText || '').trim();
      if (/^\(\d{1,6}\)$/.test(t))         { r.reviewCount = t.replace(/[^0-9]/g, ''); break; }
      if (/^([\d,]+)\s*review/i.test(t)) {
        const m = t.match(/^([\d,]+)/);
        if (m) { r.reviewCount = m[1].replace(/,/g, ''); break; }
      }
    }
  }

  // Strategy F: Reviews-tab summary panel — when the Reviews tab is already
  // open, Google shows a summary row like "5.0 ★★★★★ · 14 reviews" at the top.
  // The large rating digit and "N reviews" text are both accessible here.
  if (!r.rating || !r.reviewCount) {
    // The reviews summary section has a large number (rating) and count text.
    // Try the review-count header element that Google renders above review cards.
    const revPanel = document.querySelector('[data-review-id]');
    if (revPanel) {
      // Walk up to find the reviews container with its summary header.
      let container = revPanel.parentElement;
      while (container && container !== document.body) {
        // Look for a sibling or ancestor that contains the rating summary.
        const prev = container.previousElementSibling;
        if (prev) {
          if (!r.rating) {
            const ratingEl = prev.querySelector('[aria-hidden="true"]');
            if (ratingEl) {
              const rt = (ratingEl.innerText || '').trim();
              if (/^\d\.\d$/.test(rt)) r.rating = rt;
            }
          }
          if (!r.reviewCount) {
            for (const el of prev.querySelectorAll('span, div, button')) {
              const al = el.getAttribute('aria-label') || '';
              if (/([\d,]+)\s*review/i.test(al)) {
                const m = al.match(/([\d,]+)/);
                if (m) { r.reviewCount = m[1].replace(/,/g, ''); break; }
              }
              const t = (el.innerText || '').trim();
              if (/^([\d,]+)\s*review/i.test(t)) {
                const m = t.match(/^([\d,]+)/);
                if (m) { r.reviewCount = m[1].replace(/,/g, ''); break; }
              }
            }
          }
        }
        if (r.rating && r.reviewCount) break;
        container = container.parentElement;
      }
    }
  }

  // No visible count = 0 reviews (Google hides the count when there are none).
  if (!r.reviewCount && r.rating) r.reviewCount = '0';

  // ─── Category ─────────────────────────────────────────────────────────────
  {
    const catBtn = $('button[jsaction*="category"]');
    r.category = catBtn ? catBtn.innerText.trim() : '';
    if (!r.category) {
      for (const b of $$('button')) {
        const t = b.innerText.trim();
        if (t && t.length > 2 && t.length < 60 && !/^\d/.test(t) &&
            !/(direction|share|save|photo|review|write|send|claim|overview|about)/i.test(t)) {
          r.category = t; break;
        }
      }
    }
  }

  // ─── Address ──────────────────────────────────────────────────────────────
  r.address = '';
  {
    const addrBtn = $('button[data-item-id="address"]');
    if (addrBtn) {
      const al = addrBtn.getAttribute('aria-label') || '';
      r.address = al.replace(/^Address:\s*/i, '').trim()
                  || addrBtn.innerText.replace(/\n+/g, ' ').trim();
    }
    if (!r.address) {
      const el = $('[aria-label^="Address"]');
      if (el) r.address = (el.getAttribute('aria-label') || '').replace(/^Address:\s*/i, '').trim();
    }
    if (!r.address) {
      for (const el of $$('[data-item-id] .Io6YTe, [data-item-id] .rogA2c')) {
        const t = (el.innerText || '').trim();
        if (t.length > 10 && /\d/.test(t) && /[a-zA-Z]/.test(t)) { r.address = t; break; }
      }
    }
  }

  // ─── Phone ────────────────────────────────────────────────────────────────
  r.phone = '';
  {
    const phoneBtn = $('button[data-item-id^="phone:"]');
    if (phoneBtn) {
      const al = phoneBtn.getAttribute('aria-label') || '';
      r.phone = al.replace(/^Phone:\s*/i, '').trim()
                || phoneBtn.innerText.replace(/\n+/g, ' ').trim();
    }
    if (!r.phone) {
      const telLink = $('a[href^="tel:"]');
      if (telLink) r.phone = telLink.href.replace('tel:', '').trim() || telLink.innerText.trim();
    }
  }

  // ─── Website ──────────────────────────────────────────────────────────────
  {
    const webLink = $('a[data-item-id="authority"]');
    r.website = webLink ? (webLink.href || webLink.innerText.trim()) : '';
  }

  // ─── Plus code ────────────────────────────────────────────────────────────
  {
    const plusBtn = $('button[data-item-id="oloc"]');
    r.plusCode = plusBtn ? plusBtn.innerText.replace(/\n+/g, ' ').trim() : '';
  }

  // ─── Hours ────────────────────────────────────────────────────────────────
  r.hours = [];
  {
    const hoursTable = $('table.eK4R0e, table.y0skZc, table.WgFkxc, table');
    if (hoursTable) {
      hoursTable.querySelectorAll('tr').forEach(row => {
        const cells = row.querySelectorAll('td');
        if (cells.length >= 2) {
          const day = cells[0].innerText.trim();
          const lis = cells[1].querySelectorAll('li');
          const time = lis.length
            ? Array.from(lis).map(li => li.innerText.trim()).filter(Boolean).join(', ')
            : cells[1].innerText.trim();
          if (day && time) r.hours.push({ day, time });
        }
      });
    }
    // Fallback: aria-label attributes like "Monday, 9 am to 2 pm, Copy open hours"
    // Search document-wide — the expanded hours popup may live outside the panel.
    if (r.hours.length <= 1) {
      const dayNames = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
      const seen = new Set();
      const hoursFromAria = [];
      document.querySelectorAll('[aria-label]').forEach(el => {
        const al = el.getAttribute('aria-label') || '';
        for (const d of dayNames) {
          if ((al.startsWith(d + ',') || al.startsWith(d + ':')) && !seen.has(d)) {
            seen.add(d);
            const cleaned = al.replace(/,?\s*Copy open hours/i, '').trim().replace(/,\s*$/, '');
            const timePart = cleaned.substring(d.length).replace(/^[,:;\s]+/, '').trim();
            if (timePart) hoursFromAria.push({ day: d, time: timePart });
            break;
          }
        }
      });
      if (hoursFromAria.length > r.hours.length) r.hours = hoursFromAria;
    }
    if (!r.hours.length) {
      for (const sel of ['[aria-label*="hour" i]', '[data-hide-tooltip-on-mouse-move]']) {
        const el = $(sel);
        if (el) {
          const lbl = el.getAttribute('aria-label') || el.innerText || '';
          if (lbl.trim()) { r.hours.push({ raw: lbl.trim() }); break; }
        }
      }
    }
  }

  // ─── Open/closed status ───────────────────────────────────────────────────
  {
    const openEl = $('[data-hide-tooltip-on-mouse-move]');
    r.openNow = openEl ? openEl.innerText.trim().replace(/\n+/g, ' ').trim() : '';
  }

  // ─── About / description ──────────────────────────────────────────────────
  r.about = '';
  {
    const editSummary = $('.PYvSYb, .WeS02d, .e07Vkf');
    if (editSummary) r.about = editSummary.innerText.trim();
    if (!r.about) {
      const aboutSection = $('[aria-label*="About" i][role="tabpanel"]');
      if (aboutSection) r.about = (aboutSection.innerText || '').trim().substring(0, 2000);
    }
  }

  // ─── Service options / amenities ──────────────────────────────────────────
  r.serviceOptions = [];
  {
    $$('[data-item-id^="amenities:"] li, div.LTs0Rc span, div.E0DTEd span').forEach(el => {
      const t = (el.innerText || '').trim();
      if (t && t.length < 80 && !r.serviceOptions.includes(t)) r.serviceOptions.push(t);
    });
    $$('[data-item-id^="amenities:"]').forEach(el => {
      const al = (el.getAttribute('aria-label') || '').trim();
      if (al && !r.serviceOptions.includes(al)) r.serviceOptions.push(al);
    });
  }

  // ─── Reviews visible on the overview tab ─────────────────────────────────
  // The selector '[data-review-id], div.jftiEf, div.GHT2ce' matches elements
  // at MULTIPLE nesting levels inside the same review card, causing duplicates.
  // Fix: collect all elements with data-review-id, then keep only the outermost
  // ones (i.e. drop any element that is contained within another matched element).
  r.reviews = [];
  {
    const allRevEls = Array.from(panel.querySelectorAll('[data-review-id]'));
    // Top-level only — filter out any that are nested inside another match.
    const topRevEls = allRevEls.filter(
      el => !allRevEls.some(other => other !== el && other.contains(el))
    );
    // If no data-review-id elements found, fall back to div.jftiEf (tab panel view).
    const revEls = topRevEls.length
      ? topRevEls
      : Array.from(panel.querySelectorAll('div.jftiEf'));

    revEls.forEach(revEl => {
      // ── Author ──
      // .d4r55 / .WNxzHc is the author name span — take only the first line
      // to strip the "N reviews · N photos" badge that appears below the name.
      const authorEl = revEl.querySelector('.d4r55, .WNxzHc');
      const author   = authorEl
        ? (authorEl.innerText || '').split('\n')[0].trim()
        : '';

      // ── Rating ──
      const starsEl   = revEl.querySelector('[role="img"][aria-label*="star" i]');
      const starsLabel = starsEl ? (starsEl.getAttribute('aria-label') || '') : '';

      // ── Review text ──
      let text = '';
      for (const cls of ['.wiI7pd', '.Jtu6Td', '.MyEned', '[class*="review-text"]']) {
        const el = revEl.querySelector(cls);
        if (el) { text = (el.innerText || '').trim(); if (text) break; }
      }

      // ── Relative time ── take only the last non-empty line to skip star icons
      const timeEl  = revEl.querySelector('.rsqaWe, .DU9Pgb, [class*="publish-date"]');
      const relTime = timeEl
        ? (timeEl.innerText || '').split('\n').map(s => s.trim()).filter(Boolean).pop() || ''
        : '';

      // Only emit entries that have at least an author name or review text.
      if (author || text) {
        r.reviews.push({
          author,
          rating:       starsLabel,
          text:         text.substring(0, 1000),
          relativeTime: relTime,
        });
      }
    });
  }

  // ─── Photos count ─────────────────────────────────────────────────────────
  r.photosCount = null;
  r.photosLabel = '';
  {
    for (const sel of ['button[aria-label*="photo" i]', '[jsaction*="photo"]']) {
      const photosBtn = $(sel);
      if (photosBtn) {
        const al = photosBtn.getAttribute('aria-label') || '';
        const m  = al.match(/([\d,]+)/);
        r.photosCount = m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
        r.photosLabel = al;
        break;
      }
    }
  }

  // ─── Coordinates from URL ─────────────────────────────────────────────────
  try {
    const m = window.location.href.match(/@(-?[\d.]+),(-?[\d.]+)/);
    if (m) { r.latitude = parseFloat(m[1]); r.longitude = parseFloat(m[2]); }
  } catch(e) {}

  // ─── Place ID from URL ────────────────────────────────────────────────────
  try {
    const m = window.location.href.match(/!1s(0x[0-9a-f]+:0x[0-9a-f]+)/i);
    if (m) r.placeId = m[1];
    if (!r.placeId) {
      const m2 = window.location.href.match(/place_id[=:]([A-Za-z0-9_-]+)/);
      if (m2) r.placeId = m2[1];
    }
  } catch(e) {}

  // ─── Popular times / live busyness ───────────────────────────────────────
  r.popularTimes = '';
  {
    const busyEl = $('[aria-label*="busy" i], [aria-label*="Popular times" i]');
    if (busyEl) r.popularTimes = (busyEl.getAttribute('aria-label') || busyEl.innerText || '').trim();
  }

  return r;
}
"""


def _is_google_maps_place_url(url: str) -> bool:
    """Check if URL is a Google Maps place page."""
    return bool(re.match(r'https?://(www\.)?google\.[a-z.]+/maps/place/', url))


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


async def _dismiss_google_consent(page) -> None:
    """Dismiss Google's GDPR / cookie consent dialog if present."""
    CONSENT_SELECTORS = [
        'button[aria-label*="Accept all"]',
        'button[aria-label*="Reject all"]',
        'form[action*="consent"] button',
        'button[jsname="b3VHJd"]',           # "Accept all" jsname
        '[aria-label="Accept all"]',
        'button:has-text("Accept all")',
        'button:has-text("Reject all")',
    ]
    for sel in CONSENT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count():
                await btn.click(timeout=3000)
                await asyncio.sleep(1)
                return
        except Exception:
            continue


_GMAPS_REVIEW_EXTRACT_JS = """
() => {
  const revs = [];
  // Collect all elements with data-review-id, keep only the outermost ones
  // (nested matches cause each review to appear multiple times).
  const allRevEls = Array.from(document.querySelectorAll('[data-review-id]'));
  const topRevEls = allRevEls.filter(
    el => !allRevEls.some(other => other !== el && other.contains(el))
  );
  const revEls = topRevEls.length
    ? topRevEls
    : Array.from(document.querySelectorAll('div.jftiEf'));

  revEls.forEach(revEl => {
    const authorEl  = revEl.querySelector('.d4r55, .WNxzHc');
    // Take only the first line to strip the "N reviews · N photos" badge.
    const author    = authorEl ? (authorEl.innerText || '').split('\\n')[0].trim() : '';
    const starsEl   = revEl.querySelector('[role="img"][aria-label*="star" i]');
    const starsLabel = starsEl ? starsEl.getAttribute('aria-label') : '';
    let text = '';
    for (const cls of ['.wiI7pd', '.Jtu6Td', '.MyEned', '[class*="review-text"]']) {
      const el = revEl.querySelector(cls);
      if (el) { text = (el.innerText || '').trim(); if (text) break; }
    }
    const timeEl  = revEl.querySelector('.rsqaWe, .DU9Pgb, [class*="publish-date"]');
    const relTime = timeEl
      ? (timeEl.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).pop() || ''
      : '';
    if (author || text) {
      revs.push({ author, rating: starsLabel, text: text.substring(0, 1000), relativeTime: relTime });
    }
  });
  return revs;
}
"""


async def _scrape_gmaps_place_async(context, url: str) -> dict | None:
    """Dedicated Google Maps place scraper with proper wait & review scrolling."""
    page = await context.new_page()
    try:
        try:
            resp = await page.goto(url, wait_until="networkidle", timeout=45000)
        except PWTimeoutAsync:
            # Fallback: at least wait for DOM
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except PWTimeoutAsync:
                resp = None
        status_code = resp.status if resp else 0

        # ── Dismiss cookie/consent dialog ──
        await _dismiss_google_consent(page)

        # ── Wait for the place panel to render ──
        # h1.DUwDvf is the business name heading specific to place cards.
        # Fall back to generic selectors for alternate Maps layouts.
        for wait_sel in ['h1.DUwDvf', 'button[data-item-id="address"]', '[role="main"]', 'h1']:
            try:
                await page.wait_for_selector(wait_sel, timeout=8000)
                break
            except PWTimeoutAsync:
                continue

        # Extra settle time for AJAX-loaded details (rating, hours, etc.)
        await asyncio.sleep(3)

        # ── Normalize to Overview tab ─────────────────────────────────────────
        # URLs with !9m1!1b1 open directly on the Reviews tab.  The overview
        # data (name, address, hours, etc.) lives in the Overview panel.
        # Switch to it so that _GMAPS_PLACE_EXTRACT_JS can find h1.DUwDvf.
        try:
            active_tab_label = await page.evaluate("""() => {
                const sel = document.querySelector(
                    'button[role="tab"][aria-selected="true"]');
                return sel
                    ? (sel.getAttribute('aria-label') || sel.innerText || '')
                    : '';
            }""")
            if 'review' in active_tab_label.lower():
                overview_tab = page.locator(
                    'button[role="tab"][aria-label*="Overview" i]'
                ).first
                if await overview_tab.count():
                    await overview_tab.click()
                    await asyncio.sleep(2)
                    try:
                        await page.wait_for_selector('h1.DUwDvf', timeout=6000)
                    except PWTimeoutAsync:
                        pass
        except Exception:
            pass

        # ── Expand hours section ──
        try:
            # First click the main hours row to expand
            for sel in ['[data-hide-tooltip-on-mouse-move]', '[aria-label*="hour" i]',
                        'button[data-item-id^="oh"]']:
                hours_btn = page.locator(sel).first
                if await hours_btn.count():
                    await hours_btn.click()
                    await asyncio.sleep(1)
                    break
            # Then click "Show open hours for the week" to see all 7 days
            show_week = page.locator('[aria-label="Show open hours for the week"]').first
            if await show_week.count():
                await show_week.click()
                await asyncio.sleep(1.5)
        except Exception:
            pass

        # ── Expand "See more" for About section if present ──
        try:
            see_more = page.locator('button[aria-label*="About" i], [jsaction*="about"]').first
            if await see_more.count():
                await see_more.click()
                await asyncio.sleep(1)
        except Exception:
            pass

        # ── Extract structured Google Maps data ──
        gmaps_data: dict = {}
        try:
            gmaps_data = await page.evaluate(_GMAPS_PLACE_EXTRACT_JS)
        except Exception as exc:
            gmaps_data = {"_extractError": str(exc)}

        # ── Click Reviews tab and scroll for more reviews ──
        reviews_from_tab: list[dict] = []
        try:
            # Multiple strategies to find the Reviews tab
            reviews_tab = None
            for sel in [
                'button[role="tab"][aria-label*="Review" i]',
                'button[aria-label*="Reviews"]',
                'button[data-tab-id*="review" i]',
            ]:
                loc = page.locator(sel).first
                if await loc.count():
                    reviews_tab = loc
                    break

            if reviews_tab:
                # Extract review count from tab's aria-label BEFORE clicking
                # (e.g. aria-label="Reviews (14)" or "14 reviews")
                try:
                    tab_label = await reviews_tab.get_attribute('aria-label') or ''
                    import re as _re
                    m = _re.search(r'(\d[\d,]*)', tab_label)
                    if m:
                        tab_review_count = m.group(1).replace(',', '')
                        # Tab label count is authoritative — always override Pass 1 result
                        gmaps_data["reviewCount"] = tab_review_count
                except Exception:
                    pass

                await reviews_tab.click()
                await asyncio.sleep(2)

                # Extract review count from the reviews panel header
                # Google shows "N reviews" or "N Google reviews" at the top of the reviews tab.
                # Scope to the reviews panel ONLY — never scan all [role="main"] which
                # includes the search-results sidebar and returns stale/wrong counts.
                try:
                    rc_from_tab = await page.evaluate(r"""() => {
                        // Helper: try to extract "N" from strings like "14 reviews" or "Reviews (14)"
                        function extractCount(str) {
                            if (!str) return '';
                            // "N reviews" pattern
                            const m1 = str.match(/([\d,]+)\s*review/i);
                            if (m1) return m1[1].replace(/,/g, '');
                            // "Reviews (N)" or "Reviews · N" pattern
                            const m2 = str.match(/review[^(]*\(?(\d[\d,]*)/i);
                            if (m2) return m2[1].replace(/,/g, '');
                            return '';
                        }

                        // Strategy A: reviews-tab aria-label already has the count
                        // e.g. aria-label="Reviews (14)" — check all tab buttons
                        for (const tab of document.querySelectorAll('button[role="tab"]')) {
                            const al = tab.getAttribute('aria-label') || '';
                            if (/review/i.test(al)) {
                                const c = extractCount(al);
                                if (c) return c;
                            }
                        }

                        // Strategy B: reviews summary header — the block that shows the
                        // aggregate rating + "N reviews" text sits ABOVE the scrollable list.
                        // It is typically a sibling of div.m6QErb (the scrollable container).
                        const scrollable = document.querySelector(
                            'div.m6QErb.DxyBCb, div.m6QErb[tabindex="-1"]'
                        );
                        if (scrollable && scrollable.parentElement) {
                            const parent = scrollable.parentElement;
                            // Walk all elements in the parent (summary header siblings)
                            // but exclude the scrollable list itself
                            for (const el of parent.querySelectorAll('span, div, button')) {
                                if (scrollable.contains(el)) continue; // skip review cards
                                const al = el.getAttribute('aria-label') || '';
                                const c = extractCount(al) || extractCount((el.innerText || '').split('\n')[0]);
                                if (c) return c;
                            }
                        }

                        // Strategy C: sort button aria-label often encodes the count
                        // e.g. "Sort reviews, 14 reviews"
                        const sortBtn = document.querySelector(
                            'button[aria-label*="Sort" i], button[aria-label*="sort" i], ' +
                            'button[jsaction*="sortReviews"], button[data-value="sort"]'
                        );
                        if (sortBtn) {
                            const c = extractCount(sortBtn.getAttribute('aria-label') || '');
                            if (c) return c;
                        }

                        // Strategy D: "N Google reviews" text anywhere in the panel header
                        // (the visible heading rendered above the list, e.g. "14 Google reviews")
                        for (const el of document.querySelectorAll(
                            'div.fontTitleLarge, div.fontHeadlineSmall, div.fontBodyMedium, ' +
                            '[class*="review"] h2, [class*="review"] h3'
                        )) {
                            const t = (el.innerText || '').trim();
                            if (/review/i.test(t)) {
                                const c = extractCount(t);
                                if (c) return c;
                            }
                        }

                        return '';
                    }""")
                    # Tab-derived count is authoritative — always override whatever Pass 1 returned
                    if rc_from_tab:
                        gmaps_data["reviewCount"] = rc_from_tab
                except Exception:
                    pass

                # Find the scrollable reviews container (try multiple selectors)
                scrollable = None
                for sel in [
                    'div.m6QErb.DxyBCb.kA9KIf.dS8AEf',
                    'div.m6QErb.DxyBCb',
                    'div[role="main"] div.m6QErb',
                    '[tabindex="-1"].m6QErb',
                ]:
                    loc = page.locator(sel).first
                    if await loc.count():
                        scrollable = loc
                        break

                if scrollable:
                    # Scroll to load more reviews
                    prev_count = 0
                    for _ in range(5):
                        await scrollable.evaluate('el => el.scrollTop = el.scrollHeight')
                        await asyncio.sleep(1.5)
                        # Check if new reviews loaded
                        cur_count = await page.evaluate(
                            '() => document.querySelectorAll("[data-review-id], div.jftiEf, div.GHT2ce").length'
                        )
                        if cur_count == prev_count:
                            break  # No more reviews loading
                        prev_count = cur_count

                    # Also try to expand "More" buttons on individual reviews
                    try:
                        more_buttons = page.locator('button[aria-label="See more"], button.w8nwRe, button[aria-expanded="false"][jsaction*="review"]')
                        count = await more_buttons.count()
                        for i in range(min(count, 10)):
                            try:
                                await more_buttons.nth(i).click(timeout=1000)
                            except Exception:
                                pass
                        if count > 0:
                            await asyncio.sleep(1)
                    except Exception:
                        pass

                # Re-extract reviews after scrolling & expanding
                extra = await page.evaluate(_GMAPS_REVIEW_EXTRACT_JS)
                if isinstance(extra, list) and len(extra) > len(gmaps_data.get("reviews", [])):
                    reviews_from_tab = extra
        except Exception:
            pass

        if reviews_from_tab:
            gmaps_data["reviews"] = reviews_from_tab

        html = await page.content()
        body_text = extract_text_from_html(html)

        return {
            "url": url,
            "status_code": status_code,
            "title": (await page.title()) if hasattr(page, "title") else "",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "js_rendered": True,
            "google_maps_data": gmaps_data,
            "content_hash": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        _progress({"event": "gmaps_error", "error": str(exc)})
        return None
    finally:
        await page.close()


async def _scrape_gmaps_reviews_only(context, url: str) -> dict | None:
    """Lightweight second pass: just click Reviews tab and extract count + reviews."""
    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
        except PWTimeoutAsync:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except PWTimeoutAsync:
                pass

        await _dismiss_google_consent(page)
        await asyncio.sleep(3)

        review_count = ""
        reviews: list[dict] = []

        # Find and click the Reviews tab
        reviews_tab = None
        for sel in [
            'button[role="tab"][aria-label*="Review" i]',
            'button[aria-label*="Reviews"]',
            'button[data-tab-id*="review" i]',
        ]:
            loc = page.locator(sel).first
            if await loc.count():
                reviews_tab = loc
                break

        if not reviews_tab:
            await page.close()
            return None

        # Get review count from tab label before clicking
        try:
            tab_label = await reviews_tab.get_attribute('aria-label') or ''
            import re as _re
            m = _re.search(r'(\d[\d,]*)', tab_label)
            if m:
                review_count = m.group(1).replace(',', '')
        except Exception:
            pass

        await reviews_tab.click()
        await asyncio.sleep(2)

        # Extract review count from the reviews panel
        if not review_count:
            try:
                review_count = await page.evaluate(r"""() => {
                    const main = document.querySelector('[role="main"]');
                    if (!main) return '';
                    for (const el of main.querySelectorAll('span, div, button')) {
                        const al = el.getAttribute('aria-label') || '';
                        if (/\d+\s*review/i.test(al)) {
                            const m = al.match(/([\d,]+)/);
                            if (m) return m[1].replace(/,/g, '');
                        }
                        const t = (el.innerText || '').trim();
                        const tm = t.match(/^([\d,]+)\s*review/i);
                        if (tm) return tm[1].replace(/,/g, '');
                    }
                    const sortBtn = document.querySelector('button[aria-label*="Sort"], button[aria-label*="sort"]');
                    if (sortBtn) {
                        const al = sortBtn.getAttribute('aria-label') || '';
                        const m = al.match(/([\d,]+)/);
                        if (m) return m[1].replace(/,/g, '');
                    }
                    return '';
                }""")
            except Exception:
                pass

        # Scroll for reviews
        scrollable = None
        for sel in [
            'div.m6QErb.DxyBCb.kA9KIf.dS8AEf',
            'div.m6QErb.DxyBCb',
            'div[role="main"] div.m6QErb',
            '[tabindex="-1"].m6QErb',
        ]:
            loc = page.locator(sel).first
            if await loc.count():
                scrollable = loc
                break

        if scrollable:
            prev_count = 0
            for _ in range(5):
                await scrollable.evaluate('el => el.scrollTop = el.scrollHeight')
                await asyncio.sleep(1.5)
                cur_count = await page.evaluate(
                    '() => document.querySelectorAll("[data-review-id], div.jftiEf, div.GHT2ce").length'
                )
                if cur_count == prev_count:
                    break
                prev_count = cur_count

        # Extract reviews
        try:
            reviews = await page.evaluate(_GMAPS_REVIEW_EXTRACT_JS)
        except Exception:
            pass

        return {
            "reviewCount": review_count or "",
            "reviews": reviews if isinstance(reviews, list) else [],
        }
    except Exception:
        return None
    finally:
        await page.close()


async def scrape_google_maps_place(url: str, headless: bool = True) -> dict:
    """Top-level entry: scrape a single Google Maps place URL.

    Uses two passes:
      1. Default headless context → overview data (name, rating, address, etc.)
      2. User-agent context → Reviews tab click → review count + review text
    """
    t_start = time.time()
    if async_playwright is None:
        return {"error": "playwright async_api not available"}

    # ── URL normalisation ─────────────────────────────────────────────────────
    # URLs that embed search context (!2m1!1s<query>, !15s...) or force a
    # specific tab open (!9m1!1b1) cause headless Chromium to receive a
    # degraded "limited view" page — no tab bar, no review count, and
    # sometimes an empty place card.  Rebuild a minimal canonical place URL
    # from the CID + lat/lng embedded in the data parameter so every URL
    # variant lands on the same well-rendered place page.
    import re as _re_url

    def _canonical_gmaps_url(raw: str) -> str:
        """Return a clean place URL derived from the CID and coords in raw."""
        # Only attempt reconstruction for google.com/maps/place URLs
        if "google.com/maps/place" not in raw:
            return raw
        # Extract place name from path
        nm = _re_url.search(r'/maps/place/([^/@?]+)', raw)
        name = nm.group(1) if nm else 'place'
        # CID  (hex pair separated by colon)
        cid_m = _re_url.search(r'!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)', raw)
        # Lat/lng stored in the data segment
        coord_m = _re_url.search(r'!8m2!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', raw)
        # Fallback: coords in the path  /@lat,lng,zoom
        path_coord = _re_url.search(r'/@(-?\d+\.\d+),(-?\d+\.\d+)', raw)
        # Place ID  (!16s…)
        pid_m = _re_url.search(r'(!16s[^!?&]+)', raw)

        if not cid_m or not (coord_m or path_coord):
            # Not enough info — fall back to stripping only the known bad params
            cleaned = _re_url.sub(r'!9m1!1b1', '', raw)
            cleaned = _re_url.sub(r'!1m\d+!2m\d+!1s[^!]+', '', cleaned)
            cleaned = _re_url.sub(r'!15s[^!?&]+', '', cleaned)
            return cleaned

        cid = cid_m.group(1)
        if coord_m:
            lat, lng = coord_m.group(1), coord_m.group(2)
        else:
            lat, lng = path_coord.group(1), path_coord.group(2)

        canonical = (
            f"https://www.google.com/maps/place/{name}/@{lat},{lng},17z"
            f"/data=!3m1!4b1!4m6!3m5!1s{cid}!8m2!3d{lat}!4d{lng}"
        )
        if pid_m:
            canonical += pid_m.group(1)
        return canonical

    url = _canonical_gmaps_url(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)

        _UA = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        # ── Pass 1: Overview data ─────────────────────────────────────────────
        # Use a real user-agent so Google renders the full F7nice row including
        # the review count span (without UA it omits it, causing downstream
        # strategies to fall back to unreliable broad-scan values).
        ctx1 = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            user_agent=_UA,
        )
        result = await _scrape_gmaps_place_async(ctx1, url)
        await ctx1.close()

        # ── Pass 2: Reviews (scroll + full text) ─────────────────────────────
        # Always run Pass 2: Pass 1 may have gotten the count from an
        # unreliable broad scan.  Pass 2 uses the Reviews tab panel header
        # which is the authoritative source, and also loads more review text.
        gmaps_data = (result or {}).get("google_maps_data") or {}

        if True:  # always run
            try:
                ctx2 = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                reviews_result = await _scrape_gmaps_reviews_only(ctx2, url)
                await ctx2.close()

                if reviews_result:
                    rc = reviews_result.get("reviewCount", "")
                    if rc and rc != "0":
                        gmaps_data["reviewCount"] = rc
                    revs = reviews_result.get("reviews", [])
                    if revs and len(revs) > len(gmaps_data.get("reviews", [])):
                        gmaps_data["reviews"] = revs
                    if result:
                        result["google_maps_data"] = gmaps_data
            except Exception:
                pass

        await browser.close()

    if not result:
        return {"error": "scrape_failed", "url": url}

    result["crawl_duration_s"] = int(time.time() - t_start)
    return result


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

        # ── Google Maps place page: use dedicated extractor ──
        gmaps_data = None
        if _is_google_maps_place_url(url_norm):
            try:
                # Dismiss consent dialog first
                await _dismiss_google_consent(page)
                # Wait for key Maps elements
                for wait_sel in ['h1.DUwDvf', 'button[data-item-id="address"]', '[role="main"]', 'h1']:
                    try:
                        await page.wait_for_selector(wait_sel, timeout=6000)
                        break
                    except PWTimeoutAsync:
                        continue
                # Extra settle for Maps dynamic content
                await asyncio.sleep(3)
                # Try expanding hours
                for sel in ['[data-hide-tooltip-on-mouse-move]', '[aria-label*="hour" i]',
                            'button[data-item-id^="oh"]']:
                    try:
                        hours_btn = page.locator(sel).first
                        if await hours_btn.count():
                            await hours_btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        continue
                gmaps_data = await page.evaluate(_GMAPS_PLACE_EXTRACT_JS)
            except Exception:
                gmaps_data = None

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

        rec = {
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
        if gmaps_data:
            rec["google_maps_data"] = gmaps_data
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
