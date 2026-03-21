#!/usr/bin/env python3
"""
biz-scrape-instagram: Fetch recent posts and comments from public Instagram.

Uses Playwright to render JS, then extracts from embedded JSON (shared_data/graphql).
Falls back to insta-scrape when available and when extraction succeeds.
Output JSON compatible with biz-sentiment-analysis pipeline.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

# Prefer Playwright for reliable rendering; fallback to requests
USE_PLAYWRIGHT = True
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    USE_PLAYWRIGHT = False

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[instagram] ERROR: pip install requests beautifulsoup4")
    raise SystemExit(1)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_username(target: str) -> str:
    target = (target or "").strip().rstrip("/")
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", target, re.I)
    if m:
        return m.group(1)
    if target.startswith("@"):
        return target[1:]
    return target


def fetch_html_with_graphql(url: str) -> tuple[str | None, list[dict]]:
    """Fetch HTML and capture GraphQL responses that may contain post data."""
    graphql_data = []
    if USE_PLAYWRIGHT:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1280, "height": 900},
                    user_agent=HEADERS.get("User-Agent", ""),
                    locale="en-US",
                )
                page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})

                def on_resp(response):
                    try:
                        u = response.url
                        if "graphql" in u or "api/v1" in u or "query" in u or "__a=1" in u or "__d=dis" in u:
                            if "instagram.com" not in u:
                                return
                            body = response.json()
                            data = body.get("data", body) if isinstance(body, dict) else body
                            if isinstance(data, dict) and data:
                                graphql_data.append(data)
                            elif isinstance(body, dict) and body:
                                gq = body.get("graphql", body.get("data"))
                                if isinstance(gq, dict) and gq:
                                    graphql_data.append(gq)
                                else:
                                    graphql_data.append(body)
                    except Exception:
                        pass

                page.on("response", on_resp)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                try:
                    for _ in range(2):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.5)
                except Exception:
                    pass
                time.sleep(1)
                html = page.content()
                browser.close()
                return html, graphql_data
        except Exception:
            pass
    return None, []


def _find_timeline_edges(obj: dict | list, depth: int = 0) -> list:
    """Recursively find edge_owner_to_timeline_media.edges in nested GraphQL response."""
    if depth > 8:
        return []
    if isinstance(obj, dict):
        if "edge_owner_to_timeline_media" in obj:
            return (obj.get("edge_owner_to_timeline_media") or {}).get("edges", [])
        for v in obj.values():
            found = _find_timeline_edges(v, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_timeline_edges(item, depth + 1)
            if found:
                return found
    return []


def extract_posts_from_graphql_responses(graphql_list: list[dict], username: str) -> list[dict]:
    """Extract posts from captured GraphQL API responses."""
    posts = []
    seen_shortcodes = set()
    for data in graphql_list:
        edges = (
            (data.get("user") or {}).get("edge_owner_to_timeline_media", {}).get("edges", [])
            or _find_timeline_edges(data)
        )
        for edge in edges:
            node = edge.get("node", {})
            if not node:
                continue
            sc = node.get("shortcode", "")
            if sc in seen_shortcodes:
                continue
            seen_shortcodes.add(sc)
            cap_edges = node.get("edge_media_to_caption", {}).get("edges", [])
            caption = cap_edges[0]["node"]["text"] if cap_edges else ""
            comment_edges = node.get("edge_media_to_comment", {}).get("edges", [])
            comments = [
                {
                    "username": ce["node"].get("owner", {}).get("username", "unknown"),
                    "text": ce["node"].get("text", ""),
                    "timestamp": datetime.fromtimestamp(ce["node"]["created_at"], tz=timezone.utc).isoformat() if ce["node"].get("created_at") else None,
                }
                for ce in comment_edges[:50]
            ]
            shortcode = sc
            is_video = node.get("is_video", False)
            dr = node.get("display_resources") or []
            display_url = node.get("display_url") or node.get("thumbnail_src") or (dr[-1].get("src") if dr else None)
            video_url = node.get("video_url") if is_video else None
            posts.append({
                "shortcode": shortcode,
                "url": f"https://www.instagram.com/p/{shortcode}/",
                "display_url": display_url,
                "video_url": video_url,
                "is_video": is_video,
                "caption": caption,
                "likes_count": node.get("edge_liked_by", {}).get("count"),
                "comments_count": len(comments),
                "comments": comments,
            })
    return posts


def fetch_html(url: str) -> str | None:
    """Fetch page HTML using requests (fallback when Playwright not used)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def extract_shared_data(html: str) -> dict | None:
    m = re.search(r"window\._sharedData\s*=\s*(\{[\s\S]*?\});\s*</script>", html)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"<script[^>]*>([^<]*\"entry_data\"[^<]*)</script>", html)
    if m:
        try:
            s = m.group(1)
            start = s.find("{")
            if start >= 0:
                depth = 0
                for i, c in enumerate(s[start:], start):
                    if c == "{": depth += 1
                    elif c == "}": depth -= 1
                    if depth == 0:
                        return json.loads(s[start:i + 1])
        except Exception:
            pass
    # XHR/GraphQL blob
    for m in re.finditer(r'"graphql"\s*:\s*(\{[^{]*(?:\{[^{}]*\}[^{}]*)*\})', html):
        try:
            return {"entry_data": {"ProfilePage": [{"graphql": json.loads("{" + m.group(0))}]}}
        except Exception:
            continue
    # Embedded timeline: "edge_owner_to_timeline_media":{...}
    idx = html.find("edge_owner_to_timeline_media")
    if idx >= 0:
        for start in range(idx, max(0, idx - 500), -1):
            if html[start] == "{":
                depth, i = 0, start
                while i < min(len(html), start + 50000):
                    if html[i] == "{":
                        depth += 1
                    elif html[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                obj = json.loads(html[start : i + 1])
                                edges = _find_timeline_edges(obj)
                                if edges:
                                    return {"_graphql_obj": obj}
                            except Exception:
                                pass
                            break
                    i += 1
                break
    return None


def parse_posts_from_data(data: dict, is_post_page: bool = False) -> list[dict]:
    posts = []
    try:
        entry = data.get("entry_data", {})
        pages = entry.get("PostPage", []) if is_post_page else entry.get("ProfilePage", [])
        if not pages:
            return posts
        page = pages[0] if isinstance(pages[0], dict) else {}
        if is_post_page:
            media = page.get("graphql", {}).get("shortcode_media", {})
            if media:
                cap_edges = media.get("edge_media_to_caption", {}).get("edges", [])
                caption = cap_edges[0]["node"]["text"] if cap_edges else ""
                edges = media.get("edge_media_to_parent_comment", {}).get("edges", []) or media.get("edge_media_to_comment", {}).get("edges", [])
                comments = [{"username": e["node"].get("owner", {}).get("username", "unknown"), "text": e["node"].get("text", ""), "timestamp": None} for e in edges[:50]]
                is_video = media.get("is_video", False)
                display_url = media.get("display_url")
                video_url = media.get("video_url") if is_video else None
                posts.append({
                    "shortcode": media.get("shortcode", ""),
                    "url": f"https://www.instagram.com/p/{media.get('shortcode', '')}/",
                    "display_url": display_url,
                    "video_url": video_url,
                    "is_video": is_video,
                    "caption": caption,
                    "likes_count": media.get("edge_liked_by", {}).get("count"),
                    "comments_count": len(comments),
                    "comments": comments,
                })
            return posts
        user = page.get("graphql", {}).get("user", {}) or page.get("user", {})
        if not user:
            return posts
        edges = user.get("edge_owner_to_timeline_media", {}).get("edges", [])
        for edge in edges:
            node = edge.get("node", {})
            if not node:
                continue
            cap_edges = node.get("edge_media_to_caption", {}).get("edges", [])
            caption = cap_edges[0]["node"]["text"] if cap_edges else ""
            comment_edges = node.get("edge_media_to_comment", {}).get("edges", [])
            comments = []
            for ce in comment_edges:
                cn = ce.get("node", {})
                comments.append({
                    "username": cn.get("owner", {}).get("username", "unknown"),
                    "text": cn.get("text", ""),
                    "timestamp": datetime.fromtimestamp(cn["created_at"], tz=timezone.utc).isoformat() if cn.get("created_at") else None,
                })
            shortcode = node.get("shortcode", "")
            is_video = node.get("is_video", False)
            display_url = node.get("display_url")
            video_url = node.get("video_url") if is_video else None
            posts.append({
                "shortcode": shortcode,
                "url": f"https://www.instagram.com/p/{shortcode}/",
                "display_url": display_url,
                "video_url": video_url,
                "is_video": is_video,
                "caption": caption,
                "likes_count": node.get("edge_liked_by", {}).get("count"),
                "comments_count": node.get("edge_media_to_comment", {}).get("count", 0),
                "comments": comments,
            })
    except (IndexError, KeyError, TypeError):
        pass
    return posts


def _find_shortcode_media(obj: dict, depth: int = 0) -> dict | None:
    """Recursively find shortcode_media in nested GraphQL response."""
    if depth > 5 or not isinstance(obj, dict):
        return None
    if "shortcode_media" in obj:
        return obj.get("shortcode_media")
    for v in obj.values():
        found = _find_shortcode_media(v, depth + 1) if isinstance(v, dict) else None
        if found:
            return found
    return None


def fetch_single_post_via_playwright(post_url: str) -> dict | None:
    """Fetch a single post's data (caption, media, etc.) via Playwright + GraphQL."""
    if not USE_PLAYWRIGHT:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=HEADERS.get("User-Agent", ""),
            )
            graphql_data = []

            def on_resp(response):
                try:
                    if "graphql" in response.url or "api/v1" in response.url:
                        body = response.json()
                        data = body.get("data", body)
                        if isinstance(data, dict) and _find_shortcode_media(data):
                            graphql_data.append(data)
                except Exception:
                    pass

            page.on("response", on_resp)
            page.goto(post_url, wait_until="networkidle", timeout=15000)
            time.sleep(1)
            browser.close()

        for data in graphql_data:
            media = data.get("shortcode_media") or _find_shortcode_media(data)
            if not media:
                continue
            cap_edges = media.get("edge_media_to_caption", {}).get("edges", [])
            caption = cap_edges[0]["node"]["text"] if cap_edges else ""
            comment_edges = media.get("edge_media_to_parent_comment", {}).get("edges", []) or media.get("edge_media_to_comment", {}).get("edges", [])
            comments = [
                {"username": ce["node"].get("owner", {}).get("username", "unknown"), "text": ce["node"].get("text", ""), "timestamp": None}
                for ce in comment_edges[:50]
            ]
            shortcode = media.get("shortcode", "")
            is_video = media.get("is_video", False)
            dr = media.get("display_resources") or []
            display_url = media.get("display_url") or media.get("thumbnail_src") or (dr[-1].get("src") if dr else None)
            video_url = media.get("video_url") if is_video else None
            return {
                "shortcode": shortcode,
                "url": post_url,
                "display_url": display_url,
                "video_url": video_url,
                "is_video": is_video,
                "caption": caption,
                "likes_count": media.get("edge_liked_by", {}).get("count"),
                "comments_count": len(comments),
                "comments": comments,
            }
    except Exception:
        pass
    return None


def extract_comments_from_graphql(graphql_list: list[dict]) -> list[dict]:
    """Extract comments from GraphQL responses (PostPage shortcode_media)."""
    comments = []
    for data in graphql_list:
        if not isinstance(data, dict):
            continue
        media = data.get("shortcode_media") or _find_shortcode_media(data)
        if not media:
            continue
        edges = media.get("edge_media_to_parent_comment", {}).get("edges", []) or media.get("edge_media_to_comment", {}).get("edges", [])
        for edge in edges[:50]:
            node = edge.get("node", {})
            if not node:
                continue
            comments.append({
                "username": node.get("owner", {}).get("username", "unknown"),
                "text": node.get("text", ""),
                "timestamp": datetime.fromtimestamp(node["created_at"], tz=timezone.utc).isoformat() if node.get("created_at") else None,
            })
    return comments


def fetch_post_comments_with_playwright(shortcode: str) -> list[dict]:
    """Fetch comments from post page using Playwright + GraphQL capture (public posts show top comments)."""
    if not USE_PLAYWRIGHT:
        return []
    url = f"https://www.instagram.com/p/{shortcode}/"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            graphql_data = []

            def on_resp(response):
                try:
                    if "graphql" in response.url or "api/v1" in response.url:
                        body = response.json()
                        data = body.get("data", body)
                        if isinstance(data, dict) and _find_shortcode_media(data):
                            graphql_data.append(data)
                except Exception:
                    pass

            page.on("response", on_resp)
            page.goto(url, wait_until="networkidle", timeout=20000)
            time.sleep(1.5)
            browser.close()
            return extract_comments_from_graphql(graphql_data)
    except Exception:
        pass
    return []


def fetch_post_comments(shortcode: str, html_fetcher) -> list[dict]:
    """Fetch comments: prefer Playwright (gets top comments on public posts), fallback to HTML parsing."""
    comments = fetch_post_comments_with_playwright(shortcode)
    if comments:
        return comments
    url = f"https://www.instagram.com/p/{shortcode}/"
    html = html_fetcher(url)
    if not html:
        return []
    data = extract_shared_data(html)
    if not data:
        return []
    try:
        pages = data.get("entry_data", {}).get("PostPage", [])
        if not pages:
            return []
        media = pages[0].get("graphql", {}).get("shortcode_media", {})
        edges = media.get("edge_media_to_parent_comment", {}).get("edges", []) or media.get("edge_media_to_comment", {}).get("edges", [])
        for edge in edges[:50]:
            node = edge.get("node", {})
            comments.append({
                "username": node.get("owner", {}).get("username", "unknown"),
                "text": node.get("text", ""),
                "timestamp": datetime.fromtimestamp(node["created_at"], tz=timezone.utc).isoformat() if node.get("created_at") else None,
            })
    except (IndexError, KeyError, TypeError):
        pass
    return comments


def extract_post_links_from_html(html: str, max_links: int = 12) -> list[str]:
    """Extract /p/SHORTCODE/ links from profile page HTML (fallback when GraphQL empty)."""
    shortcodes = []
    for m in re.finditer(r'instagram\.com/p/([A-Za-z0-9_-]+)', html):
        sc = m.group(1)
        if sc not in shortcodes and len(sc) >= 8:
            shortcodes.append(sc)
            if len(shortcodes) >= max_links:
                break
    return [f"https://www.instagram.com/p/{sc}/" for sc in shortcodes]


def scrape_with_bs4(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    og_image = None
    og_url = ""
    for meta in soup.find_all("meta", property="og:image"):
        if meta.get("content"):
            og_image = meta["content"]
            break
    for meta in soup.find_all("meta", property="og:url"):
        if meta.get("content"):
            og_url = meta["content"]
            break
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "{}")
            if isinstance(ld, dict) and ld.get("description"):
                posts.append({
                    "shortcode": "jsonld",
                    "url": ld.get("mainEntityofPage", og_url),
                    "display_url": ld.get("image", og_image),
                    "video_url": None,
                    "is_video": False,
                    "caption": ld["description"],
                    "comments_count": 0,
                    "comments": [],
                })
        except Exception:
            pass
    if not posts:
        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            posts.append({
                "shortcode": "og",
                "url": og_url,
                "display_url": og_image,
                "video_url": None,
                "is_video": False,
                "caption": og["content"],
                "comments_count": 0,
                "comments": [],
            })
    return posts


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Instagram scraper")
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-posts", type=int, default=5)
    args = parser.parse_args()

    username = extract_username(args.target)
    max_posts = min(args.max_posts, 12)
    is_post = "/p/" in args.target and "instagram.com" in args.target.lower()
    target_url = args.target if is_post else f"https://www.instagram.com/{username}/"

    html = None
    graphql_responses = []
    if USE_PLAYWRIGHT:
        html, graphql_responses = fetch_html_with_graphql(target_url)
    if not html:
        html = fetch_html(target_url)
    if not html:
        result = {
            "platform": "instagram",
            "username": username,
            "posts_scraped": 0,
            "total_comments": 0,
            "posts": [],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "note": "Failed to fetch profile. Account may be private or blocked.",
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"[instagram] Failed → {args.output}")
        return

    posts = extract_posts_from_graphql_responses(graphql_responses, username) if graphql_responses and not is_post else []
    if not posts:
        data = extract_shared_data(html)
        if data:
            if "_graphql_obj" in data:
                posts = extract_posts_from_graphql_responses([data["_graphql_obj"]], username)
            else:
                posts = parse_posts_from_data(data, is_post_page=is_post)
    if not posts and not is_post:
        post_urls = extract_post_links_from_html(html, max_links=max_posts)
        for url in post_urls[:max_posts]:
            p = fetch_single_post_via_playwright(url)
            if p:
                posts.append(p)
                if len(posts) >= max_posts:
                    break
            time.sleep(1)
    if not posts and not is_post:
        posts = scrape_with_bs4(html)

    posts = posts[:max_posts]

    for post in posts:
        sc = post.get("shortcode", "")
        if sc and sc not in ("jsonld", "og") and len(post.get("comments", [])) < 5:
            more = fetch_post_comments(sc, fetch_html)
            if len(more) > len(post.get("comments", [])):
                post["comments"] = more
            time.sleep(1.5)

    total_comments = sum(len(p.get("comments", [])) for p in posts)
    note = None
    if total_comments == 0:
        note = "No comments extracted. Instagram may require auth or profile may be private."

    result = {
        "platform": "instagram",
        "username": username,
        "posts_scraped": len(posts),
        "total_comments": total_comments,
        "posts": posts,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[instagram] Done: {len(posts)} posts, {total_comments} comments → {args.output}")


if __name__ == "__main__":
    main()
