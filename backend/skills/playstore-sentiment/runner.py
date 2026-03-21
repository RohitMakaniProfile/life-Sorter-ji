#!/usr/bin/env python3
"""
playstore-sentiment: Fetch Play Store app metadata, rating distribution (histogram),
and latest reviews per star rating using google-play-scraper.
"""

import re
import sys
import json
import time
from typing import Any, Dict, List, Optional


def extract_app_id(target: str) -> str:
    """Extract app ID from message/URL or return as-is if already an ID."""
    target = (target or "").strip().rstrip("/")
    m = re.search(r"play\.google\.com/store/apps/details\?id=([A-Za-z0-9_.]+)", target)
    if m:
        return m.group(1)
    m = re.search(r"id=([A-Za-z0-9_.]+)", target)
    if m:
        return m.group(1)
    return target


def parse_distribution(s: str) -> Dict[int, int]:
    """Parse distribution string like '1:2,2:2,3:5,4:5,5:1' -> {1:2, 2:2, 3:5, 4:5, 5:1}."""
    default = {1: 2, 2: 2, 3: 5, 4: 5, 5: 1}
    if not s or not s.strip():
        return default
    try:
        out = {}
        for part in s.split(","):
            part = part.strip()
            if ":" in part:
                star, count = part.split(":", 1)
                out[int(star.strip())] = max(0, int(count.strip()))
        return out if out else default
    except (ValueError, TypeError):
        return default


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    args = payload.get("args") or {}
    target = args.get("appId") or payload.get("message", "").strip()
    country = (args.get("country") or "in").strip().lower()
    lang = (args.get("lang") or "en").strip().lower()
    distribution_str = args.get("distribution") or "1:2,2:2,3:5,4:5,5:1"

    app_id = extract_app_id(target)
    if not app_id:
        out: Dict[str, Any] = {
            "text": "playstore-sentiment: missing appId or target",
            "error": "missing_target",
        }
        print(json.dumps(out))
        return

    distribution = parse_distribution(distribution_str)

    try:
        from google_play_scraper import app, reviews
    except ImportError:
        out = {
            "text": "playstore-sentiment: pip install google-play-scraper",
            "error": "missing_dependency",
        }
        print(json.dumps(out))
        return

    try:
        result = app(app_id, lang=lang, country=country)
    except Exception as e:
        out = {
            "text": f"playstore-sentiment error: {e}",
            "error": "playstore_fetch_failed",
        }
        print(json.dumps(out))
        return

    hist = result.get("histogram") or [0, 0, 0, 0, 0]
    hist_map = {i + 1: hist[i] for i in range(5)}

    collected: List[Dict[str, Any]] = []
    for star, count in sorted(distribution.items()):
        if count <= 0 or star < 1 or star > 5:
            continue
        try:
            revs, _ = reviews(
                app_id,
                lang=lang,
                country=country,
                count=count * 3,
                filter_score_with=star,
            )
            taken = 0
            for r in revs:
                if taken >= count:
                    break
                if r.get("score") != star:
                    continue
                collected.append({
                    "rating": star,
                    "text": (r.get("content") or ""),
                    "userName": r.get("userName"),
                    "thumbsUpCount": r.get("thumbsUpCount"),
                    "at": r.get("at"),
                })
                taken += 1
            time.sleep(0.5)
        except Exception as e:
            pass

    lines = [
        "Play Store sentiment snapshot",
        "",
        f"App: {result.get('title', '')}",
        f"Developer: {result.get('developer', '')}",
        f"Average rating: {result.get('score')} (from {result.get('ratings', 0):,} ratings)",
        f"Installs: {result.get('installs', '')}",
        f"Category: {result.get('genre', '')}",
        "",
        "Rating distribution (from store):",
    ]
    for s in range(1, 6):
        lines.append(f"  {s} star: {hist_map.get(s, 0):,}")
    lines.append("")
    lines.append(f"Reviews sampled (per requested distribution {distribution_str}): {len(collected)}")
    lines.append("")

    for r in collected:
        stars = "★" * r["rating"] + "☆" * (5 - r["rating"])
        text = (r.get("text") or "")[:500]
        lines.append(f"{stars} | {text}")
        lines.append("")

    text = "\n".join(lines).strip()

    def _serialize(v: Any) -> Any:
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        if isinstance(v, (list, tuple)):
            return [_serialize(x) for x in v]
        if isinstance(v, dict):
            return {str(k): _serialize(x) for k, x in v.items()}
        return str(v)

    reviews_clean = [
        {k: _serialize(r.get(k)) for k in ("rating", "text", "userName", "thumbsUpCount", "at")}
        for r in collected
    ]

    out_data: Dict[str, Any] = {
        "appId": app_id,
        "title": result.get("title"),
        "developer": result.get("developer"),
        "score": result.get("score"),
        "ratings": result.get("ratings"),
        "installs": result.get("installs"),
        "genre": result.get("genre"),
        "histogram": hist_map,
        "distribution_requested": distribution_str,
        "reviews_collected": reviews_clean,
    }

    out: Dict[str, Any] = {"text": text, "data": out_data}
    s = json.dumps(out, ensure_ascii=False)
    print(s, flush=True)


if __name__ == "__main__":
    main()
