#!/usr/bin/env python3
"""
Comment scraper: Fetch comments for a YouTube video using Playwright.

Loads the video page, intercepts InnerTube API responses, and extracts commentRenderer.
Falls back to requests + InnerTube continuation when Playwright unavailable.

Usage:
    python3 comment_scraper.py --video-id XXX --output comments.json
    python3 comment_scraper.py --video-url "https://youtube.com/watch?v=XXX" --output comments.json
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import requests
except ImportError:
    requests = None

USE_PLAYWRIGHT = True
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    USE_PLAYWRIGHT = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/next"


def _find_all_comment_renderers(obj, depth=0, max_depth=14) -> list:
    """Recursively find commentRenderer dicts. Handles commentThreadRenderer, reloadContinuationItemsCommand."""
    if depth > max_depth:
        return []
    out = []
    if isinstance(obj, dict):
        if "commentRenderer" in obj:
            out.append(obj.get("commentRenderer", obj))
        if "commentThreadRenderer" in obj:
            ct = obj["commentThreadRenderer"]
            for r in ct.get("replies", {}).get("commentRepliesRenderer", {}).get("contents", []):
                if "commentRenderer" in r:
                    out.append(r["commentRenderer"])
            if "comment" in ct and "commentRenderer" in ct["comment"]:
                out.append(ct["comment"]["commentRenderer"])
        # onResponseReceivedEndpoints[].reloadContinuationItemsCommand.continuationItems
        if "continuationItems" in obj:
            for item in obj["continuationItems"] or []:
                out.extend(_find_all_comment_renderers(item, depth + 1, max_depth))
        if "reloadContinuationItemsCommand" in obj:
            out.extend(_find_all_comment_renderers(obj["reloadContinuationItemsCommand"], depth + 1, max_depth))
        for v in obj.values():
            out.extend(_find_all_comment_renderers(v, depth + 1, max_depth))
    elif isinstance(obj, list):
        for x in obj:
            out.extend(_find_all_comment_renderers(x, depth + 1, max_depth))
    return out


def _parse_comment_renderer(r: dict) -> dict | None:
    """Parse commentRenderer to {author, text, likes, published_time}."""
    if not isinstance(r, dict):
        return None
    content = r.get("contentText", {})
    text = content.get("simpleText", "") or "".join(x.get("text", "") for x in content.get("runs", []))
    if not text:
        return None
    author_el = r.get("authorText", {})
    author = author_el.get("simpleText", "") or "".join(x.get("text", "") for x in author_el.get("runs", [])) or "unknown"
    likes_txt = r.get("voteCount", {}).get("simpleText", "")
    likes = int(re.sub(r"[^0-9]", "", likes_txt)) if likes_txt and re.sub(r"[^0-9]", "", likes_txt) else None
    pub = r.get("publishedTimeText", {}).get("runs", [])
    published = pub[0].get("text", "") if pub else ""
    return {"author": author, "text": text, "likes": likes, "published_time": published or None}


def _extract_comments_from_dom(page, max_comments: int) -> list[dict]:
    """Extract comments from YouTube comment section DOM (ytd-comment-thread-renderer)."""
    comments = []
    try:
        # Wait for comment threads to appear
        page.wait_for_selector("ytd-comment-thread-renderer, #contents ytd-comment-thread-renderer", timeout=10000)
    except Exception:
        pass
    try:
        threads = page.query_selector_all("ytd-comment-thread-renderer")
        for thread in threads[:max_comments]:
            try:
                author_el = thread.query_selector("#author-text span, #author-text")
                author = (author_el.inner_text().strip() if author_el else "") or "unknown"
                text_el = thread.query_selector("#content-text, #expander-contents")
                text = (text_el.inner_text().strip() if text_el else "") or ""
                if not text:
                    continue
                like_el = thread.query_selector("#vote-count-middle")
                likes = None
                if like_el:
                    raw = like_el.inner_text().strip().replace(",", "")
                    if raw.isdigit():
                        likes = int(raw)
                time_el = thread.query_selector("#published-time-text a, #published-time-text")
                published = (time_el.inner_text().strip() if time_el else "") or None
                comments.append({"author": author, "text": text, "likes": likes, "published_time": published})
            except Exception:
                continue
    except Exception:
        pass
    return comments


def fetch_comments_playwright(video_url: str, max_comments: int = 50) -> list[dict]:
    """Load video page with Playwright: try network interception, then DOM scraping."""
    if not USE_PLAYWRIGHT:
        return []
    comments = []
    seen_text = set()

    def on_response(response):
        nonlocal comments
        try:
            u = response.url
            if "youtube.com" not in u or ("youtubei" not in u and "next" not in u and "browse" not in u):
                return
            if response.request.resource_type not in ("fetch", "xhr"):
                return
            body = response.json()
            for r in _find_all_comment_renderers(body):
                c = _parse_comment_renderer(r if isinstance(r, dict) and "contentText" in r else r.get("commentRenderer", r))
                if c and c["text"] and c["text"] not in seen_text:
                    seen_text.add(c["text"])
                    comments.append(c)
                    if len(comments) >= max_comments:
                        return
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=HEADERS["User-Agent"],
            )
            page.on("response", on_response)
            page.goto(video_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(2)
            # Scroll to comments section so it loads
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)
            page.evaluate("document.querySelector('ytd-comments')?.scrollIntoView()")
            time.sleep(2)
            # Prefer DOM extraction (reliable when comments are visible)
            dom_comments = _extract_comments_from_dom(page, max_comments)
            if dom_comments:
                comments = dom_comments
            browser.close()
    except Exception:
        pass
    return comments[:max_comments]


def extract_continuation_from_html(html: str) -> str | None:
    """Find comments continuation token in page HTML."""
    # Comments section continuation
    m = re.search(r'"continuationCommand"\s*:\s*\{[^}]*"token"\s*:\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    # Alternative patterns
    for pat in [
        r'"reloadContinuationData"\s*:\s*\{[^}]*"continuation"\s*:\s*"([^"]+)"',
        r'"continuation"\s*:\s*"([^"]{50,})"',
    ]:
        for m in re.finditer(pat, html):
            t = m.group(1)
            if "Eg" in t or len(t) > 80:  # Likely comment continuation
                return t
    return None


def fetch_page(url: str) -> str | None:
    if not requests:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def fetch_comments_innertube(html: str, video_id: str, max_comments: int = 50) -> list[dict]:
    """Fetch comments via InnerTube continuation API (requests fallback)."""
    if not requests:
        return []
    token = extract_continuation_from_html(html)
    if not token:
        return []
    try:
        payload = {
            "context": {
                "client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00", "hl": "en", "gl": "US"}
            },
            "continuation": token,
        }
        resp = requests.post(
            f"{INNERTUBE_URL}?key={INNERTUBE_KEY}",
            json=payload,
            headers={"User-Agent": HEADERS["User-Agent"], "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        comments = []
        seen = set()
        for r in _find_all_comment_renderers(resp.json()):
            c = _parse_comment_renderer(r if isinstance(r, dict) and "contentText" in r else r.get("commentRenderer", r))
            if c and c["text"] and c["text"] not in seen:
                seen.add(c["text"])
                comments.append(c)
                if len(comments) >= max_comments:
                    break
        return comments
    except Exception:
        return []


def extract_comments_from_initial_data(html: str) -> list[dict]:
    """Extract server-rendered comments from ytInitialData in HTML."""
    m = re.search(r"var\s+ytInitialData\s*=\s*(\{[\s\S]*?\});\s*</script>", html)
    if not m:
        m = re.search(r'window\["ytInitialData"\]\s*=\s*(\{[\s\S]*?\});', html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        comments = []
        seen = set()
        for r in _find_all_comment_renderers(data):
            c = _parse_comment_renderer(r if isinstance(r, dict) and "contentText" in r else r.get("commentRenderer", r))
            if c and c["text"] and c["text"] not in seen:
                seen.add(c["text"])
                comments.append(c)
        return comments
    except Exception:
        return []


def fetch_comments_ytdlp(video_url: str, max_comments: int = 50) -> list[dict]:
    """Fetch comments via yt-dlp (requires writecomments; may need JS runtime for YouTube)."""
    try:
        import yt_dlp
        opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "writecomments": True,
            "extractor_args": {"youtube": {"max_comments": [str(max_comments)], "comment_sort": ["top"]}},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False, process=True)
        raw = info.get("comments") or []
        comments = []
        for c in raw[:max_comments]:
            if isinstance(c, dict):
                comments.append({
                    "author": c.get("author", c.get("author_id", "unknown")),
                    "text": c.get("text", ""),
                    "likes": c.get("like_count"),
                    "published_time": c.get("timestamp"),
                })
            elif isinstance(c, str):
                comments.append({"author": "unknown", "text": c, "likes": None, "published_time": None})
        return comments
    except Exception:
        return []


def fetch_comments_for_video(video_id: str | None, video_url: str | None, max_comments: int = 50) -> list[dict]:
    """Fetch comments: try Playwright, then yt-dlp, then requests + InnerTube."""
    url = video_url or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
    if not url:
        return []
    comments = fetch_comments_playwright(url, max_comments)
    if comments:
        return comments
    comments = fetch_comments_ytdlp(url, max_comments)
    if comments:
        return comments
    html = fetch_page(url)
    if not html:
        return []
    comments = extract_comments_from_initial_data(html)
    if not comments and video_id:
        comments = fetch_comments_innertube(html, video_id, max_comments)
    return comments


def main():
    parser = argparse.ArgumentParser(description="YouTube comment scraper")
    parser.add_argument("--video-id")
    parser.add_argument("--video-url")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-comments", type=int, default=50)
    args = parser.parse_args()
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", args.video_url or "")
    vid = args.video_id or (m.group(1) if m else None)
    comments = fetch_comments_for_video(vid, args.video_url, args.max_comments)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"comments": comments, "count": len(comments)}, f, indent=2, ensure_ascii=False)
    print(f"[comment_scraper] {len(comments)} comments → {args.output}")


if __name__ == "__main__":
    main()
