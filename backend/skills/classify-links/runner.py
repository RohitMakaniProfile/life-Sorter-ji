#!/usr/bin/env python3
"""
classify-links: bucket URLs into platform categories.
"""

import json
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def extract_urls(text: str) -> List[str]:
  if not text:
    return []
  urls = URL_RE.findall(text)
  # also handle comma/newline separated inputs that may not match URL_RE (rare)
  raw_parts = re.split(r"[\s,\n]+", text.strip())
  for p in raw_parts:
    if p.startswith("http://") or p.startswith("https://"):
      urls.append(p)
  # de-dupe preserve order
  out: List[str] = []
  seen = set()
  for u in urls:
    u2 = u.strip().rstrip(").,]")
    if not u2 or u2 in seen:
      continue
    seen.add(u2)
    out.append(u2)
  return out


def bucket_url(url: str) -> str:
  u = url.lower()

  # Maps / local listings
  if "google.com/maps" in u or "maps.google." in u or "g.page" in u:
    return "google_maps"

  # Food delivery / restaurant aggregators (India + global)
  if "zomato." in u:
    return "zomato"
  if "swiggy." in u:
    return "swiggy"
  if "ubereats." in u:
    return "ubereats"
  if "doordash." in u:
    return "doordash"

  # Travel / hotels
  if "booking.com" in u:
    return "booking"
  if "tripadvisor." in u:
    return "tripadvisor"
  if "airbnb." in u:
    return "airbnb"
  if "expedia." in u:
    return "expedia"

  # General reviews
  if "trustpilot." in u:
    return "trustpilot"
  if "yelp." in u:
    return "yelp"
  if "glassdoor." in u:
    return "glassdoor"

  # SaaS review sites
  if u.startswith("https://www.g2.com") or "g2.com/products" in u:
    return "g2"
  if "capterra." in u:
    return "capterra"

  # Marketplaces (starter set)
  if "amazon." in u:
    return "amazon"
  if "flipkart." in u:
    return "flipkart"
  if "etsy." in u:
    return "etsy"

  # Social
  if "instagram.com" in u:
    return "instagram"
  if "youtube.com" in u or "youtu.be" in u:
    return "youtube"
  if "tiktok.com" in u:
    return "tiktok"
  if "facebook.com" in u:
    return "facebook"
  if "x.com" in u or "twitter.com" in u:
    return "x"
  if "linkedin.com" in u:
    return "linkedin"

  # App stores
  if "play.google.com" in u:
    return "playstore"
  if "apps.apple.com" in u:
    return "appstore"

  return "website_or_other"

def _domain(url: str) -> str:
  try:
    return urllib.parse.urlparse(url).netloc.lower()
  except Exception:
    return ""

def _parse_taxonomy(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  raw = args.get("taxonomyJson")
  if not isinstance(raw, str) or not raw.strip():
    return None
  try:
    return json.loads(raw)
  except Exception:
    return None

def _bucket_by_taxonomy(url: str, taxonomy: Dict[str, Any]) -> Optional[str]:
  """
  taxonomy shape (from platform-taxonomy):
  { categories: [{id,...}], domainRules: [{domainContains, categoryId}] }
  We return categoryId when a rule matches; otherwise None.
  """
  rules = taxonomy.get("domainRules") if isinstance(taxonomy, dict) else None
  if not isinstance(rules, list) or not rules:
    return None
  d = _domain(url)
  u = url.lower()
  for r in rules:
    if not isinstance(r, dict):
      continue
    dc = r.get("domainContains")
    cid = r.get("categoryId")
    if not isinstance(cid, str) or not cid:
      continue
    if isinstance(dc, str) and dc:
      if dc.lower() in d or dc.lower() in u:
        return cid
  return None


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  taxonomy = _parse_taxonomy(args) or {}
  urls_text = (args.get("urls") or "").strip()
  if not urls_text:
    urls_text = payload.get("message", "")

  urls = extract_urls(urls_text)
  buckets: Dict[str, List[str]] = {}
  for u in urls:
    b = _bucket_by_taxonomy(u, taxonomy) if taxonomy else None
    if not b:
      b = bucket_url(u)
    buckets.setdefault(b, []).append(u)

  text_lines = [
    "Link classification",
    f"- URLs: {len(urls)}",
    "",
  ]
  for k in sorted(buckets.keys()):
    text_lines.append(f"- {k}: {len(buckets[k])}")
  text = "\n".join(text_lines).strip()

  out: Dict[str, Any] = {
    "text": text,
    "data": {
      "total": len(urls),
      "buckets": buckets,
      "usedTaxonomy": bool(taxonomy),
    },
  }
  print(json.dumps(out))


if __name__ == "__main__":
  main()

