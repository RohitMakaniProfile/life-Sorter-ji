#!/usr/bin/env python3
"""
biz-scrape-playstore: Fetch app reviews and ratings from Google Play Store.
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[playstore] ERROR: Missing dependencies. Run: pip3 install requests beautifulsoup4")
    raise SystemExit(1)


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}


# ------------------------------------------------------------
# Target resolution
# ------------------------------------------------------------

def extract_app_id(target: str) -> str:
    target = target.strip().rstrip("/")

    m = re.search(r"play\.google\.com/store/apps/details\?id=([A-Za-z0-9_.]+)", target)
    if m:
        return m.group(1)

    m = re.search(r"id=([A-Za-z0-9_.]+)", target)
    if m:
        return m.group(1)

    return target


# ------------------------------------------------------------
# Page fetching
# ------------------------------------------------------------

def fetch_playstore_page(app_id: str, lang: str, country: str):

    url = f"https://play.google.com/store/apps/details?id={app_id}&hl={lang}&gl={country}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.text
    except requests.RequestException:
        pass

    return None


# ------------------------------------------------------------
# Metadata extraction
# ------------------------------------------------------------

def extract_app_metadata(html):

    soup = BeautifulSoup(html, "html.parser")

    app_name = None
    h1 = soup.find("h1")
    if h1:
        span = h1.find("span")
        app_name = span.get_text(strip=True) if span else h1.get_text(strip=True)

    rating = None
    m = re.search(r'Rated\s+([0-9.]+)\s+stars', html)
    if m:
        rating = float(m.group(1))

    return {"app_name": app_name, "average_rating": rating}


# ------------------------------------------------------------
# Review walker
# ------------------------------------------------------------

def _walk_for_reviews(data, reviews):

    if isinstance(data, list):

        # New Play Store pattern
        try:
            # Typical structure: [..., author, ..., rating, ..., review_text, ...]
            if (
                len(data) > 10
                and isinstance(data[0], list)
                and isinstance(data[0][1], str)
            ):
                author = data[0][1]

                rating = None
                text = None

                # scan list for rating + text
                for item in data:
                    if isinstance(item, int) and 1 <= item <= 5:
                        rating = item

                    if isinstance(item, str) and len(item) > 20:
                        text = item

                if author and rating and text:
                    reviews.append({
                        "author": author,
                        "rating": rating,
                        "text": text,
                        "date": None,
                        "thumbs_up": None,
                    })
                    return
        except:
            pass

        for item in data:
            _walk_for_reviews(item, reviews)

    elif isinstance(data, dict):
        for v in data.values():
            _walk_for_reviews(v, reviews)


# ------------------------------------------------------------
# Batch API
# ------------------------------------------------------------

def fetch_reviews_batch_by_rating(app_id, lang, country, star_rating, count):

    reviews = []

    try:

        url = "https://play.google.com/_/PlayStoreUi/data/batchexecute"

        inner = json.dumps([app_id, None, 1, star_rating, [count, None, None], [1]])

        payload = {
            "f.req": json.dumps([
                [
                    [
                        "UsvDTd",
                        inner,
                        None,
                        "generic"
                    ]
                ]
            ])
        }
        r = requests.post(
            f"{url}?hl={lang}&gl={country}",
            data=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            timeout=15,
        )

        if r.status_code != 200:
            return []

        for line in r.text.split("\n"):

            line = line.strip()

            if line.startswith("["):
                try:
                    data = json.loads(line)
                    _walk_for_reviews(data, reviews)
                except:
                    pass

    except:
        pass

    filtered = [r for r in reviews if r.get("rating") == star_rating]

    return filtered[:count]


# ------------------------------------------------------------
# Distribution parsing
# ------------------------------------------------------------

def parse_distribution(dist_string):

    default = {1:1,2:1,3:1,4:1,5:1}

    try:
        result = {}

        for pair in dist_string.split(","):
            star,count = pair.split(":")
            result[int(star)] = int(count)

        return result

    except:
        print("[playstore] Invalid distribution format. Using default.")
        return default


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--country", default="us")

    parser.add_argument(
        "--distribution",
        default="1:1,2:1,3:1,4:1,5:1",
        help="Review distribution e.g. 1:2,2:3,3:5,4:5,5:1"
    )

    args = parser.parse_args()

    review_distribution = parse_distribution(args.distribution)

    app_id = extract_app_id(args.target)

    print(f"[playstore] Scraping {app_id}")

    html = fetch_playstore_page(app_id, args.lang, args.country)

    if not html:
        print("[playstore] Failed to fetch page")
        return

    metadata = extract_app_metadata(html)

    reviews = []
    existing = set()

    # --------------------------------------------------------
    # Controlled star sampling
    # --------------------------------------------------------

    for star, count in review_distribution.items():

        print(f"[playstore] Fetching {count} reviews with {star}★")

        star_reviews = fetch_reviews_batch_by_rating(
            app_id,
            args.lang,
            args.country,
            star,
            count*3
        )

        added = 0

        for r in star_reviews:

            key = r["text"][:80]

            if key not in existing:

                r["filter_source"] = f"{star}_star"

                reviews.append(r)
                existing.add(key)

                added += 1

            if added >= count:
                break

        print(f"[playstore] Added {added}/{count}")

        time.sleep(1)

    result = {
        "platform": "playstore",
        "app_id": app_id,
        "app_name": metadata["app_name"],
        "average_rating": metadata["average_rating"],
        "total_reviews": len(reviews),
        "reviews": reviews,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[playstore] Done → {args.output}")


if __name__ == "__main__":
    main()