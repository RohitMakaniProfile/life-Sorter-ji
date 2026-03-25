#!/usr/bin/env python3
"""
Video scraper: Fetch video list and metadata from YouTube channels or single videos.

Uses youtube-channel-scraper (Selenium) with fallback to requests + ytInitialData.
Exports: video_id, url, title, description, author, published_at, thumbnail, view_count.
Does NOT fetch comments (use comment_scraper for that).

Usage:
    python3 video_scraper.py --target "https://youtube.com/@channel" --max-videos 5 --output videos.json
    python3 video_scraper.py --target "https://youtube.com/watch?v=XXX" --output video.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Allow imports from sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import requests
except ImportError:
    requests = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

USE_YT_CHANNEL_SCRAPER = True
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    USE_YT_CHANNEL_SCRAPER = False


def _build_browser(proxy_ip=None):
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def resolve_target(target: str) -> dict:
    target = (target or "").strip().rstrip("/")
    if m := re.search(r"[?&]v=([A-Za-z0-9_-]{11})", target):
        return {"type": "video", "value": m.group(1)}
    if m := re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", target):
        return {"type": "video", "value": m.group(1)}
    if m := re.search(r"youtube\.com/channel/(UC[A-Za-z0-9_-]+)", target):
        return {"type": "channel", "value": f"https://www.youtube.com/channel/{m.group(1)}"}
    if m := re.search(r"youtube\.com/@([A-Za-z0-9_.]+)", target):
        return {"type": "channel", "value": f"https://www.youtube.com/@{m.group(1)}"}
    if target.startswith("@"):
        return {"type": "channel", "value": f"https://www.youtube.com/{target}"}
    if re.match(r"^[A-Za-z0-9_-]{11}$", target):
        return {"type": "video", "value": target}
    if "youtube.com" in target or target.startswith("http"):
        return {"type": "channel", "value": target}
    return {"type": "channel", "value": f"https://www.youtube.com/@{target}"}


def fetch_page(url: str) -> str | None:
    if not requests:
        return None
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
    return None


def extract_yt_initial_data(html: str) -> dict | None:
    for pat in [r"var\s+ytInitialData\s*=\s*(\{[\s\S]*?\});\s*</script>", r'window\["ytInitialData"\]\s*=\s*(\{[\s\S]*?\});']:
        if m := re.search(pat, html):
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return None


def find_all_by_key(obj, key: str, max_n: int = 100) -> list:
    results = []
    if isinstance(obj, dict):
        if key in obj:
            results.append(obj[key])
        for v in obj.values():
            results.extend(find_all_by_key(v, key, max_n - len(results))[: max_n - len(results)])
    elif isinstance(obj, list):
        for x in obj:
            results.extend(find_all_by_key(x, key, max_n - len(results))[: max_n - len(results)])
    return results[:max_n]


def extract_video_ids_from_channel(data: dict) -> list[str]:
    ids = []
    try:
        tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
        for tab in tabs:
            c = tab.get("tabRenderer", {}).get("content", {})
            for item in c.get("richGridRenderer", {}).get("contents", []):
                if vid := item.get("richItemRenderer", {}).get("content", {}).get("videoRenderer", {}).get("videoId"):
                    ids.append(vid)
            for sec in c.get("sectionListRenderer", {}).get("contents", []):
                for item in sec.get("itemSectionRenderer", {}).get("contents", []):
                    vid = item.get("gridVideoRenderer", {}).get("videoId") or item.get("videoRenderer", {}).get("videoId")
                    if vid:
                        ids.append(vid)
    except (AttributeError, TypeError):
        pass
    seen = set()
    return [x for x in ids if x not in seen and not seen.add(x)]


def extract_video_details(data: dict) -> dict:
    out = {"description": None, "author": None, "published_at": None, "view_count": None}
    try:
        r = data.get("contents", {}).get("twoColumnWatchNextResults", {}).get("results", {}).get("results", {})
        for c in r.get("contents", []):
            primary = c.get("videoPrimaryInfoRenderer", {})
            secondary = c.get("videoSecondaryInfoRenderer", {})
            if primary:
                out["view_count"] = primary.get("viewCount", {}).get("videoViewCountRenderer", {}).get("viewCount", {}).get("simpleText", "")
                if date_el := primary.get("dateText", {}):
                    out["published_at"] = date_el.get("simpleText", "") or "".join(x.get("text", "") for x in date_el.get("runs", []))
            if secondary:
                owner = secondary.get("owner", {}).get("videoOwnerRenderer", {})
                if owner:
                    out["author"] = "".join(x.get("text", "") for x in owner.get("title", {}).get("runs", []))
                desc = secondary.get("attributedDescription", {}) or secondary.get("description", {}) or {}
                out["description"] = desc.get("simpleText", "") or "".join(x.get("text", "") for x in desc.get("runs", []))
                if not out["description"]:
                    out["description"] = "".join(s.get("text", "") for s in secondary.get("snippet", {}).get("runs", []))
    except (AttributeError, TypeError):
        pass
    return out


def scrape_single_video(video_id: str) -> dict:
    url = f"https://www.youtube.com/watch?v={video_id}"
    html = fetch_page(url)
    title, details = None, {}
    if html and (data := extract_yt_initial_data(html)):
        r = data.get("contents", {}).get("twoColumnWatchNextResults", {}).get("results", {}).get("results", {})
        for c in r.get("contents", []):
            if p := c.get("videoPrimaryInfoRenderer", {}):
                title = "".join(x.get("text", "") for x in p.get("title", {}).get("runs", []))
                break
        details = extract_video_details(data)
    return {
        "video_id": video_id,
        "url": url,
        "title": title,
        "description": details.get("description"),
        "author": details.get("author"),
        "published_at": details.get("published_at"),
        "view_count": details.get("view_count"),
        "thumbnail": f"https://i3.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "comments_count": 0,
        "comments": [],
    }


def scrape_channel_package(channel_url: str, max_videos: int) -> list[dict]:
    if not USE_YT_CHANNEL_SCRAPER:
        return []
    try:
        import youtube_channel_scraper.scraper as mod
        orig = getattr(mod, "build_browser", None)
        mod.build_browser = lambda p=None: _build_browser(p)
        from youtube_channel_scraper.scraper import YoutubeScraper
        scraper = YoutubeScraper(channel_url, max_videos=max_videos)
        raw = scraper.scrape()
        if getattr(scraper, "browser", None):
            scraper.browser.quit()
        if orig:
            mod.build_browser = orig
        return [
            {
                "video_id": (m.group(1) if (m := re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v.get("url", "") or "")) else None),
                "url": v.get("url", ""),
                "title": v.get("title"),
                "description": v.get("description"),
                "author": v.get("author"),
                "published_at": v.get("published_at"),
                "view_count": None,
                "thumbnail": v.get("thumbnail"),
                "comments_count": 0,
                "comments": [],
            }
            for v in raw
        ]
    except Exception:
        return []


def scrape_channel_fallback(channel_url: str, max_videos: int) -> list[dict]:
    url = channel_url.rstrip("/") + ("/videos" if "/videos" not in channel_url else "")
    html = fetch_page(url)
    if not html or not (data := extract_yt_initial_data(html)):
        return []
    ids = extract_video_ids_from_channel(data)
    return [scrape_single_video(vid) for vid in ids[:max_videos]]


def scrape_videos(target: str, max_videos: int = 5) -> list[dict]:
    """Main entry: scrape videos from channel or single video."""
    resolved = resolve_target(target)
    max_videos = min(max_videos, 12)
    if resolved["type"] == "video":
        return [scrape_single_video(resolved["value"])]
    channel_url = resolved["value"]
    videos = scrape_channel_package(channel_url, max_videos)
    if not videos:
        videos = scrape_channel_fallback(channel_url, max_videos)
    return videos


def main():
    parser = argparse.ArgumentParser(description="YouTube video scraper")
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-videos", type=int, default=5)
    args = parser.parse_args()
    videos = scrape_videos(args.target, args.max_videos)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"videos": videos}, f, indent=2, ensure_ascii=False)
    print(f"[video_scraper] {len(videos)} videos → {args.output}")


if __name__ == "__main__":
    main()
