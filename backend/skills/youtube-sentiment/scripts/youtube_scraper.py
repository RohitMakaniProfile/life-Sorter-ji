#!/usr/bin/env python3
"""
YouTube sentiment master scraper: orchestrates video_scraper + comment_scraper.

1. Fetches video list and metadata via video_scraper
2. Fetches comments for each video via comment_scraper (Playwright)
3. Assembles final output JSON

Usage:
    python3 youtube_scraper.py --target "https://youtube.com/@channel" --output output.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from video_scraper import scrape_videos, resolve_target
from comment_scraper import fetch_comments_for_video


def run(target: str, output_path: str, max_videos: int = 5, fetch_comments: bool = True) -> dict:
    """Run full pipeline: videos + comments."""
    resolved = resolve_target(target)
    max_videos = min(max_videos, 12)

    videos = scrape_videos(target, max_videos)
    if not videos:
        return {
            "platform": "youtube",
            "target": resolved.get("value", target),
            "target_type": resolved.get("type", "channel"),
            "videos_scraped": 0,
            "total_comments": 0,
            "videos": [],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "note": "No videos found. Ensure channel/video is public.",
        }

    if fetch_comments:
        for i, v in enumerate(videos):
            comments = fetch_comments_for_video(
                v.get("video_id"),
                v.get("url"),
                max_comments=max(10, 3),  # At least 3 comments per video for sentiment
            )
            videos[i]["comments"] = comments
            videos[i]["comments_count"] = len(comments)
            if i < len(videos) - 1:
                time.sleep(1)

    total_comments = sum(v.get("comments_count", 0) for v in videos)
    result = {
        "platform": "youtube",
        "target": resolved.get("value", target),
        "target_type": resolved.get("type", "channel"),
        "videos_scraped": len(videos),
        "total_comments": total_comments,
        "videos": videos,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "note": None if total_comments > 0 else "No comments extracted. YouTube may load comments dynamically.",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="YouTube sentiment master scraper")
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-videos", type=int, default=5)
    parser.add_argument("--fetch-comments", action="store_true", default=True)
    parser.add_argument("--no-fetch-comments", action="store_false", dest="fetch_comments")
    args = parser.parse_args()

    result = run(
        target=args.target,
        output_path=args.output,
        max_videos=args.max_videos,
        fetch_comments=args.fetch_comments,
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    v = result["videos_scraped"]
    c = result["total_comments"]
    print(f"[youtube] Done: {v} videos, {c} comments → {args.output}")


if __name__ == "__main__":
    main()
