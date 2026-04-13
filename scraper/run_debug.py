#!/usr/bin/env python3
"""Test review count extraction with anti-detection."""
import sys, asyncio, json, traceback
sys.path.insert(0, "app")

URL = "https://www.google.com/maps/place/Shivam+Dental+Clinic/@23.0145287,72.5279935,17z/data=!3m1!4b1!4m6!3m5!1s0x395e875cbf7173cd:0xc009176096d734a4!8m2!3d23.0145287!4d72.5305684!16s"

async def main():
    from playwright_scraper import scrape_google_maps_place
    result = await scrape_google_maps_place(URL)
    gd = result.get("google_maps_data", {})
    output = {
        "name": gd.get("name"),
        "rating": gd.get("rating"),
        "reviewCount": gd.get("reviewCount"),
        "category": gd.get("category"),
        "reviews_count": len(gd.get("reviews", [])),
    }
    with open("/tmp/gmaps_final.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

try:
    asyncio.run(main())
except Exception:
    with open("/tmp/gmaps_final.json", "w") as f:
        json.dump({"error": traceback.format_exc()}, f)
