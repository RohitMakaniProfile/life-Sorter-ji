#!/usr/bin/env python3
"""
biz-scrape-bs4: BeautifulSoup recursive website crawler.
Performs fast static HTML crawling of a website and all discoverable internal pages.
No JavaScript rendering — use biz-scrape-playwright for JS-heavy sites.

Output JSON schema:
{
  "base_url": str,
  "pages": [
    {
      "url": str,
      "depth": int,
      "status_code": int,
      "title": str,
      "meta_description": str,
      "meta_keywords": str,
      "h1": [str],
      "h2": [str],
      "h3": [str],
      "body_text": str,          # cleaned visible text
      "links_internal": [str],   # full URLs
      "links_external": [str],
      "images_alt": [str],
      "schema_types": [str],     # JSON-LD @type values
      "canonical": str,
      "robots": str,             # meta robots content
      "content_hash": str,       # SHA256 of body_text for dedup
      "scraped_at": str          # ISO timestamp
    }
  ],
  "sitemap_urls": [str],         # if sitemap.xml found
  "robots_txt": str,
  "stats": {
    "total_pages": int,
    "failed_pages": int,
    "skipped_pages": int,
    "crawl_duration_s": float
  }
}
"""

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

class TextExtractor(HTMLParser):
    """Strip HTML tags and return visible text."""
    SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip == 0:
            text = data.strip()
            if text:
                self.parts.append(text)

    def get_text(self):
        return " ".join(self.parts)


def _attr(attrs, name):
    for k, v in attrs:
        if k == name:
            return v or ""
    return ""


def _parse_page(html: str, base_url: str) -> dict:
    parsed = urllib.parse.urlparse(base_url)
    base_domain = parsed.netloc.lower()

    data = {
        "title": "",
        "meta_description": "",
        "meta_keywords": "",
        "h1": [], "h2": [], "h3": [],
        "body_text": "",
        "links_internal": [],
        "links_external": [],
        "images_alt": [],
        "schema_types": [],
        "canonical": "",
        "robots": "",
    }

    # --- title ---
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        data["title"] = re.sub(r"\s+", " ", m.group(1)).strip()

    # --- meta tags ---
    for meta_m in re.finditer(r"<meta\s([^>]*)>", html, re.I | re.S):
        attrs_str = meta_m.group(1)
        name_m = re.search(r'name=["\']([^"\']+)["\']', attrs_str, re.I)
        content_m = re.search(r'content=["\']([^"\']*)["\']', attrs_str, re.I)
        prop_m = re.search(r'property=["\']([^"\']+)["\']', attrs_str, re.I)
        if content_m:
            content = content_m.group(1).strip()
            name = (name_m.group(1) if name_m else "").lower()
            prop = (prop_m.group(1) if prop_m else "").lower()
            if name == "description":
                data["meta_description"] = content
            elif name == "keywords":
                data["meta_keywords"] = content
            elif name == "robots":
                data["robots"] = content

    # --- canonical ---
    can_m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
    if not can_m:
        can_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', html, re.I)
    if can_m:
        data["canonical"] = can_m.group(1).strip()

    # --- headings ---
    for level in (1, 2, 3):
        tag = f"h{level}"
        for hm in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.I | re.S):
            text = re.sub(r"<[^>]+>", "", hm.group(1)).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                data[f"h{level}"].append(text)

    # --- links ---
    for lm in re.finditer(r'<a\s[^>]*href=["\']([^"\'#][^"\']*)["\']', html, re.I):
        href = lm.group(1).strip()
        if href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue
        full = urllib.parse.urljoin(base_url, href).split("#")[0].split("?")[0]
        link_parsed = urllib.parse.urlparse(full)
        if link_parsed.scheme not in ("http", "https"):
            continue
        if link_parsed.netloc.lower().endswith(base_domain) or link_parsed.netloc.lower() == base_domain:
            if full not in data["links_internal"]:
                data["links_internal"].append(full)
        else:
            if full not in data["links_external"]:
                data["links_external"].append(full)

    # --- images ---
    for im in re.finditer(r'<img\s[^>]*alt=["\']([^"\']*)["\']', html, re.I):
        alt = im.group(1).strip()
        if alt:
            data["images_alt"].append(alt)

    # --- JSON-LD schema types ---
    for jm in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            obj = json.loads(jm.group(1))
            if isinstance(obj, dict):
                t = obj.get("@type")
                if isinstance(t, str):
                    data["schema_types"].append(t)
                elif isinstance(t, list):
                    data["schema_types"].extend(t)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        t = item.get("@type")
                        if isinstance(t, str):
                            data["schema_types"].append(t)
        except Exception:
            pass

    # --- body text ---
    extractor = TextExtractor()
    extractor.feed(html)
    data["body_text"] = re.sub(r"\s+", " ", extractor.get_text()).strip()[:50000]

    return data


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",
}


def fetch(url: str, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return status, ""
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            return status, resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def fetch_robots(base_url: str) -> str:
    robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
    _, content = fetch(robots_url, timeout=8)
    return content


def fetch_sitemap_urls(base_url: str) -> list[str]:
    urls = []
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap.txt"):
        sitemap_url = urllib.parse.urljoin(base_url, path)
        _, content = fetch(sitemap_url, timeout=8)
        if not content:
            continue
        found = re.findall(r"<loc>(.*?)</loc>", content, re.I | re.S)
        urls.extend(u.strip() for u in found)
        if urls:
            break
    return list(dict.fromkeys(urls))


# ---------------------------------------------------------------------------
# Robots.txt compliance
# ---------------------------------------------------------------------------

def build_robots_parser(base_url: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception:
        pass
    return rp


# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".tar", ".gz", ".exe", ".dmg",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".ico", ".xml",
    ".json", ".csv", ".xlsx", ".docx",
}


def should_skip_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""
    return ext in SKIP_EXTENSIONS


def crawl(base_url: str, max_pages: int, max_depth: int, respect_robots: bool) -> dict:
    t_start = time.time()

    # Normalize base URL
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    robots_parser = build_robots_parser(base_url) if respect_robots else None
    robots_txt = fetch_robots(base_url)
    sitemap_urls = fetch_sitemap_urls(base_url)

    visited = set()
    failed = 0
    skipped = 0
    pages = []

    # Seed queue with base URL + sitemap URLs (up to 50 seeded)
    queue = deque()
    queue.append((base_url, 0))
    for su in sitemap_urls[:50]:
        sp = urllib.parse.urlparse(su)
        if sp.netloc.lower() == base_domain or sp.netloc.lower().endswith("." + base_domain):
            queue.append((su, 1))

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()

        # Normalize
        url = url.rstrip("/") or url
        if url in visited:
            continue
        visited.add(url)

        if should_skip_url(url):
            skipped += 1
            continue

        if respect_robots and robots_parser and not robots_parser.can_fetch("*", url):
            skipped += 1
            continue

        if depth > max_depth:
            skipped += 1
            continue

        status, html = fetch(url)
        if not html:
            if status != 200:
                failed += 1
            continue

        page_data = _parse_page(html, url)
        content_hash = hashlib.sha256(page_data["body_text"].encode("utf-8")).hexdigest()

        page_record = {
            "url": url,
            "depth": depth,
            "status_code": status,
            **page_data,
            "content_hash": content_hash,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        pages.append(page_record)

        # Enqueue discovered internal links at next depth
        if depth < max_depth:
            for link in page_data["links_internal"]:
                link_norm = link.rstrip("/") or link
                if link_norm not in visited:
                    queue.append((link_norm, depth + 1))

        # Throttle
        time.sleep(0.3)

    return {
        "base_url": base_url,
        "pages": pages,
        "sitemap_urls": sitemap_urls,
        "robots_txt": robots_txt[:5000],
        "stats": {
            "total_pages": len(pages),
            "failed_pages": failed,
            "skipped_pages": skipped,
            "crawl_duration_s": round(time.time() - t_start, 2),
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BeautifulSoup recursive website crawler")
    parser.add_argument("--url", required=True, help="Target website URL")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--max-pages", type=int, default=150, help="Max pages to crawl (default: 150)")
    parser.add_argument("--max-depth", type=int, default=4, help="Max link depth (default: 4)")
    parser.add_argument("--no-robots", action="store_true", help="Ignore robots.txt")
    args = parser.parse_args()

    print(f"[bs4-scraper] Starting crawl: {args.url} (max={args.max_pages} pages, depth={args.max_depth})")
    result = crawl(args.url, args.max_pages, args.max_depth, not args.no_robots)
    print(f"[bs4-scraper] Done: {result['stats']['total_pages']} pages in {result['stats']['crawl_duration_s']}s")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[bs4-scraper] Output written: {args.output}")


if __name__ == "__main__":
    main()

