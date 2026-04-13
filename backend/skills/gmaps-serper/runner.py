#!/usr/bin/env python3
"""
gmaps-serper: Google Maps business data via Serper Maps API.

Input (stdin JSON):
{
  "message": "<optional free-text>",
  "args": {
    "query": "Business Name City"  OR  "https://www.google.com/maps/place/...",
    "location": "Ahmedabad"  OR  "23.014,72.527"  (optional),
    "gl": "in",   (optional, default "in")
    "num": 5      (optional, default 5)
  }
}

Output (stdout JSON):
{
  "text": "...",
  "data": {
    "place": { ...structured business data... },
    "allResults": [ ...all returned places... ],
    "query": "...",
    "source": "serper_maps"
  }
}
"""
import json
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_gmaps_url(s: str) -> bool:
    return bool(re.match(r'https?://(www\.)?google\.[a-z.]+/maps/place/', s))


def _extract_from_gmaps_url(url: str) -> Tuple[str, str, str]:
    """Return (place_name, lat, lng) from a Google Maps place URL."""
    name_match = re.search(r'/maps/place/([^/@]+)', url)
    place_name = urllib.parse.unquote_plus(name_match.group(1)) if name_match else ""
    coord_match = re.search(r'@(-?[\d.]+),(-?[\d.]+)', url)
    lat = coord_match.group(1) if coord_match else ""
    lng = coord_match.group(2) if coord_match else ""
    return place_name, lat, lng


def _build_ll(location: str) -> Optional[str]:
    """Convert 'lat,lng' or city name into Serper ll param if lat/lng."""
    if not location:
        return None
    m = re.match(r'^(-?[\d.]+),\s*(-?[\d.]+)$', location.strip())
    if m:
        return f"@{m.group(1)},{m.group(2)},15z"
    return None  # city names passed as part of query instead


def _normalise_hours(raw: Any) -> List[Dict[str, str]]:
    """Normalise Serper openingHours into [{day, time}, ...] list."""
    if not raw:
        return []
    # Serper returns a dict: {"Monday": "9 AM–9 PM", ...}
    if isinstance(raw, dict):
        return [{"day": day, "time": time} for day, time in raw.items()]
    # fallback for list format
    if isinstance(raw, list):
        out = []
        for h in raw:
            if isinstance(h, dict):
                out.append({"day": h.get("day", ""), "time": h.get("hours", "")})
            elif isinstance(h, str):
                out.append({"raw": h})
        return out
    return [{"raw": str(raw)}]


def _build_place(p: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Map a Serper place object to our canonical google_maps_data shape."""
    return {
        "name":        p.get("title", ""),
        "rating":      str(p.get("rating", "")),
        "reviewCount": str(p.get("ratingCount", "")),
        "category":    (p.get("types") or [p.get("type", "")])[0] if p.get("types") else p.get("type", ""),
        "allTypes":    p.get("types", []),
        "address":     p.get("address", ""),
        "phone":       p.get("phoneNumber", ""),
        "website":     p.get("website", ""),
        "plusCode":    p.get("plusCode", ""),
        "hours":       _normalise_hours(p.get("openingHours")),
        "openNow":     str(p.get("openState") or ""),
        "about":       p.get("description") or "",
        "serviceOptions": [],
        "bookingLinks":   p.get("bookingLinks") or [],
        "reviews":     [],
        "photosCount": None,
        "thumbnailUrl": p.get("thumbnailUrl", ""),
        "latitude":    p.get("latitude", ""),
        "longitude":   p.get("longitude", ""),
        "placeId":     p.get("placeId", ""),
        "cid":         p.get("cid", ""),
        "fid":         p.get("fid", ""),
        "mapsUrl":     (
            f"https://www.google.com/maps/place/?q=place_id:{p['placeId']}"
            if p.get("placeId") else ""
        ),
        "serperQuery": query,
        "source":      "serper_maps",
    }


# ── Main API call ─────────────────────────────────────────────────────────────

def serper_maps(
    query: str,
    ll: Optional[str] = None,
    gl: str = "in",
    num: int = 5,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    api_key = os.environ.get("SERPER_API_KEY") or os.environ.get("GOOGLE_SERPER_API_KEY")
    if not api_key:
        return {"error": "SERPER_API_KEY is not set in environment"}

    body: Dict[str, Any] = {"q": query, "gl": gl, "num": num}
    if ll:
        body["ll"] = ll

    resp = requests.post(
        "https://google.serper.dev/maps",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    args    = payload.get("args") or {}
    query   = (args.get("query") or payload.get("message") or "").strip()
    location = (args.get("location") or "").strip()
    gl      = (args.get("gl") or "in").strip()
    try:
        num = int(args.get("num") or 5)
    except Exception:
        num = 5
    num = max(1, min(num, 20))

    if not query:
        print(json.dumps({"text": "gmaps-serper: missing query", "error": "missing_query"}))
        return

    # ── If a Google Maps URL is given, extract the place name & coords ──
    ll: Optional[str] = None
    if _is_gmaps_url(query):
        place_name, lat, lng = _extract_from_gmaps_url(query)
        if lat and lng:
            ll = f"@{lat},{lng},15z"
        query = place_name  # use name as the search query

    # ── Location hint from explicit location arg ──
    if not ll and location:
        ll = _build_ll(location)
        if not ll:
            # city name: append to query
            query = f"{query} {location}"

    # ── Call Serper Maps API ──
    try:
        result = serper_maps(query, ll=ll, gl=gl, num=num)
    except requests.HTTPError as e:
        print(json.dumps({
            "text": f"gmaps-serper: Serper API error — {e}",
            "error": "serper_http_error",
        }))
        return
    except Exception as e:
        print(json.dumps({
            "text": f"gmaps-serper: request failed — {e}",
            "error": "serper_request_error",
        }))
        return

    places: List[Dict[str, Any]] = result.get("places") or []
    if not places:
        print(json.dumps({
            "text": f"gmaps-serper: no results found for '{query}'",
            "error": "no_results",
            "data": {"query": query, "place": None, "allResults": [], "source": "serper_maps"},
        }))
        return

    # ── Pick best match ──
    best = places[0]
    for p in places:
        if query.lower() in (p.get("title") or "").lower():
            best = p
            break

    place = _build_place(best, query)

    # ── Build human-readable summary ──
    lines = [f"**{place['name']}** — Google Maps data (via Serper):"]
    if place["rating"]:
        lines.append(f"- ⭐ Rating: {place['rating']} ({place['reviewCount']} reviews)")
    if place["category"]:
        lines.append(f"- 🏷️ Category: {place['category']}")
    if place["address"]:
        lines.append(f"- 📍 Address: {place['address']}")
    if place["phone"]:
        lines.append(f"- 📞 Phone: {place['phone']}")
    if place["website"]:
        lines.append(f"- 🌐 Website: {place['website']}")
    if place["openNow"]:
        lines.append(f"- 🕐 {place['openNow']}")
    if place["hours"]:
        hours_str = "; ".join(
            f"{h['day']}: {h['time']}" if h.get("day") else h.get("raw", "")
            for h in place["hours"][:7]
        )
        lines.append(f"- 🕑 Hours: {hours_str}")
    if place["mapsUrl"]:
        lines.append(f"- 🔗 Maps: {place['mapsUrl']}")

    out: Dict[str, Any] = {
        "text": "\n".join(lines),
        "data": {
            "place": place,
            "allResults": [
                {
                    "title":       p.get("title", ""),
                    "address":     p.get("address", ""),
                    "rating":      p.get("rating", ""),
                    "reviewCount": p.get("ratingCount", ""),
                    "placeId":     p.get("placeId", ""),
                }
                for p in places
            ],
            "query":  query,
            "source": "serper_maps",
        },
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()

