#!/usr/bin/env python3
"""
business-scan: fetch a single URL and extract business signals + outbound presence links.
"""

import json
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup


UA = (
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def _safe_text(s: str) -> str:
  return " ".join((s or "").split()).strip()


def extract_first_url(text: str) -> str:
  if not text:
    return ""
  m = URL_RE.search(text)
  return m.group(0) if m else ""


def classify_category(text: str) -> List[str]:
  t = (text or "").lower()
  cats: List[Tuple[str, List[str]]] = [
    ("restaurant_food", ["menu", "order online", "reservations", "dine-in", "delivery", "zomato", "swiggy"]),
    ("hotel_travel", ["hotel", "rooms", "book now", "check-in", "check out", "stay", "resort", "booking.com", "tripadvisor"]),
    ("saas_b2b", ["pricing", "docs", "api", "integrations", "request a demo", "case studies", "enterprise"]),
    ("ecommerce_d2c", ["add to cart", "shop", "collections", "free shipping", "returns", "checkout"]),
    ("logistics_3pl", ["fulfilment", "fulfillment", "warehousing", "3pl", "freight", "shipping", "last mile"]),
    ("education", ["course", "curriculum", "admissions", "students", "learn", "classes"]),
    ("healthcare", ["clinic", "hospital", "patients", "appointment", "doctor"]),
  ]
  hits: List[str] = []
  for cat, kws in cats:
    if any(k in t for k in kws):
      hits.append(cat)
  return hits[:4]


def normalize_url(base: str, href: str) -> str:
  if not href:
    return ""
  href = href.strip()
  if href.startswith("//"):
    href = "https:" + href
  if href.startswith("/"):
    return urllib.parse.urljoin(base, href)
  return href


def bucket_url(url: str) -> str:
  u = url.lower()
  if "instagram.com" in u: return "instagram"
  if "youtube.com" in u or "youtu.be" in u: return "youtube"
  if "facebook.com" in u: return "facebook"
  if "linkedin.com" in u: return "linkedin"
  if "x.com" in u or "twitter.com" in u: return "x"
  if "play.google.com" in u: return "playstore"
  if "apps.apple.com" in u: return "appstore"
  if "google.com/maps" in u or "g.page" in u: return "google_maps"
  if "zomato." in u: return "zomato"
  if "swiggy." in u: return "swiggy"
  if "tripadvisor." in u: return "tripadvisor"
  if "booking.com" in u: return "booking"
  if "trustpilot." in u: return "trustpilot"
  return "other"


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  url = (args.get("url") or "").strip()
  if not url:
    url = extract_first_url(payload.get("message", ""))

  if not url:
    print(json.dumps({"text": "business-scan: missing url", "error": "missing_url"}))
    return

  try:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    resp.raise_for_status()
  except Exception as e:
    print(json.dumps({"text": f"business-scan failed to fetch url: {e}", "error": "fetch_failed"}))
    return

  soup = BeautifulSoup(resp.text, "html.parser")
  title = _safe_text(soup.title.get_text() if soup.title else "")
  meta_desc = ""
  md = soup.find("meta", attrs={"name": "description"})
  if md and md.get("content"):
    meta_desc = _safe_text(md.get("content"))

  # Pull a small amount of visible text for heuristics
  h1 = _safe_text((soup.find("h1").get_text() if soup.find("h1") else ""))
  h2s = [_safe_text(x.get_text()) for x in soup.find_all("h2")[:6]]
  visible = "\n".join([title, meta_desc, h1, "\n".join(h2s)])

  # Extract outbound links
  links: Dict[str, List[str]] = {}
  base = url
  for a in soup.find_all("a"):
    href = a.get("href") or ""
    href = normalize_url(base, href)
    if not href.startswith("http"):
      continue
    b = bucket_url(href)
    links.setdefault(b, [])
    if href not in links[b]:
      links[b].append(href)

  categories = classify_category(visible + "\n" + resp.text[:20000])
  parsed = urllib.parse.urlparse(url)
  domain = parsed.netloc

  text_lines = [
    "Business scan (landing page)",
    f"- URL: {url}",
    f"- Domain: {domain}",
    f"- Title: {title or '(none)'}",
  ]
  if meta_desc:
    text_lines.append(f"- Meta description: {meta_desc[:160]}")
  if categories:
    text_lines.append(f"- Category hints: {', '.join(categories)}")
  # Presence summary counts
  presence_keys = [k for k in links.keys() if k not in ("other",)]
  if presence_keys:
    text_lines.append("- Presence links found:")
    for k in sorted(presence_keys):
      text_lines.append(f"  - {k}: {len(links.get(k, []))}")

  out: Dict[str, Any] = {
    "text": "\n".join(text_lines).strip(),
    "data": {
      "url": url,
      "domain": domain,
      "title": title,
      "metaDescription": meta_desc,
      "h1": h1,
      "h2": [x for x in h2s if x],
      "categoryHints": categories,
      "links": links,
    },
  }
  print(json.dumps(out))


if __name__ == "__main__":
  main()

