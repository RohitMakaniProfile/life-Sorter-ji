"""URL filtering, normalisation, link parsing, and sitemap discovery."""

import json
import re
import urllib.parse
import urllib.request

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".tar", ".gz", ".exe", ".dmg",
    ".css", ".woff", ".woff2", ".ttf", ".ico",
    ".xml", ".json",
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


def _is_blog_url(url: str) -> bool:
    return "blog" in url.lower()


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
        # Only accept exact domain match — skip subdomains
        if lp.netloc.lower() == base_domain.lower():
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
            # Only accept exact domain match — skip subdomains
            if parsed.netloc.lower() == base_domain.lower():
                if not should_skip_url(u):
                    urls.append(u)
        if urls:
            break
    return list(dict.fromkeys(urls))