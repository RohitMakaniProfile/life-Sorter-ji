#!/usr/bin/env python3
"""
find-platform-handles: Discover Instagram, YouTube, and Play Store handles/pages for a business via Google search.

Input (stdin JSON from loader):
{
  "message": "<user message>",
  "args": {
    "platforms": "instagram,youtube,playstore"  # optional, comma-separated ids
  },
  ...
}

Output (stdout JSON):
{
  "text": "<human-readable summary>",
  "data": {
    "platforms": [
      {
        "platform": "instagram|youtube|playstore",
        "url": "<candidate url>",
        "confidence": 0.0-1.0,
        "reason": "<short explanation>"
      },
      ...
    ]
  }
}
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import urllib.parse
import urllib.request

import requests


PLATFORM_DOMAINS = {
  "instagram": "instagram.com",
  "youtube": "youtube.com",
  "playstore": "play.google.com",
}


@dataclass
class PlatformResult:
  platform: str
  url: str
  confidence: float
  reason: str


def _http_get(url: str, timeout: float = 10.0) -> str:
  """Very small helper for GET requests with a basic header."""
  req = urllib.request.Request(
    url,
    headers={
      "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
      )
    },
  )
  with urllib.request.urlopen(req, timeout=timeout) as resp:
    return resp.read().decode("utf-8", errors="ignore")


def discover_links_on_site(business_url: str) -> Dict[str, List[str]]:
  """
  Fetch the business website (if any URL present in the message) and try to
  detect linked Instagram / YouTube / Play Store URLs directly from its HTML.
  This is often more reliable than Google search alone.
  """
  out: Dict[str, List[str]] = {k: [] for k in PLATFORM_DOMAINS.keys()}
  if not business_url:
    return out

  try:
    html = _http_get(business_url, timeout=12.0)
  except Exception:
    return out

  # Normalize to lowercase for scanning, but keep original substrings for URLs.
  # Extract hrefs that contain any known platform domain.
  for platform, domain in PLATFORM_DOMAINS.items():
    pattern = rf'href=["\']([^"\']*{re.escape(domain)}[^"\']*)["\']'
    for m in re.finditer(pattern, html, re.I):
      url = m.group(1).strip()
      # Resolve relative URLs against the business_url if needed
      if not url.startswith("http"):
        url = urllib.parse.urljoin(business_url, url)
      if url not in out[platform]:
        out[platform].append(url)

  return out


def infer_platforms_from_message(message: str) -> List[str]:
  msg = message.lower()
  platforms: List[str] = []
  if any(w in msg for w in ["instagram", "insta", "ig"]):
    platforms.append("instagram")
  if any(w in msg for w in ["youtube", "yt", "video report", "video analysis"]):
    platforms.append("youtube")
  if any(w in msg for w in ["play store", "playstore", "android app", "apk", "google play"]):
    platforms.append("playstore")

  # If the user asks for a deep / full / multi-channel analysis,
  # enable all known platforms by default.
  if not platforms and any(
    w in msg
    for w in [
      "deep analysis",
      "full report",
      "complete report",
      "all in one",
      "all-in-one",
      "business strategy",
      "multi channel",
      "multi-channel",
    ]
  ):
    return ["instagram", "youtube", "playstore"]

  return platforms


def extract_business_name(message: str) -> str:
  """
  Try a naive heuristic for business/brand name:
  - Look for a bare domain in the message and use its hostname without TLD.
  - Otherwise, fall back to a short, cleaned version of the message.
  """
  # Find first URL-like token
  url_match = re.search(r"https?://[^\s]+", message)
  if url_match:
    url = url_match.group(0)
    try:
      parsed = urllib.parse.urlparse(url)
      host = parsed.hostname or ""
      host = host.lower()
      for prefix in ("www.", "m.", "beta."):
        if host.startswith(prefix):
          host = host[len(prefix):]
      # Take the first label as brand-ish (e.g. curiousjr.com → curiousjr)
      label = host.split(".")[0]
      if label:
        return label
    except Exception:
      pass

  # Fallback: short cleaned phrase from message
  cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", message)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  return cleaned[:80]


def google_search(business: str, platform: str, limit: int = 5) -> List[Tuple[str, str]]:
  """
  Search for platform-specific URLs using the Serper.dev API when configured,
  falling back to HTML scraping if API credentials are not present.
  Returns list of (url, snippet) tuples for matching platform domain.
  """
  domain = PLATFORM_DOMAINS[platform]
  query = f'site:{domain} {business}'
  # Preferred path: Serper.dev JSON API
  serper_key = os.environ.get("SERPER_API_KEY") or os.environ.get("GOOGLE_SERPER_API_KEY")
  if serper_key:
    try:
      resp = requests.post(
        "https://google.serper.dev/search",
        headers={
          "X-API-KEY": serper_key,
          "Content-Type": "application/json",
        },
        json={
          "q": query,
          "gl": "in",
          "num": limit,
        },
        timeout=10.0,
      )
      data = resp.json()
    except Exception:
      data = {}
    items = data.get("organic") or []
    results: List[Tuple[str, str]] = []
    for item in items:
      link = str(item.get("link") or "")
      if domain not in link:
        continue
      snippet = str(item.get("snippet") or "")
      results.append((link, snippet))
    return results

  # Fallback: HTML-based search (less reliable, but no API key needed)
  url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "num": str(limit)})
  html = _http_get(url)

  # Very rough extraction of result URLs/snippets
  results: List[Tuple[str, str]] = []
  for m in re.finditer(r'<a href="/url\?q=([^"&]+)[^>]*>(.*?)</a>', html, re.I | re.S):
    target = urllib.parse.unquote(m.group(1))
    if domain not in target:
      continue
    # Strip tracking parameters
    target = target.split("&")[0]
    snippet_match = re.search(r"<span[^>]*>(.*?)</span>", m.group(2), re.I | re.S)
    snippet = ""
    if snippet_match:
      snippet = re.sub(r"<[^>]+>", " ", snippet_match.group(1))
      snippet = re.sub(r"\s+", " ", snippet).strip()
    results.append((target, snippet))
  return results


def score_candidate(business: str, platform: str, url: str, snippet: str) -> float:
  """
  Heuristic confidence score based on URL + snippet matching the business name.
  """
  biz = business.lower()
  score = 0.3  # base if we at least matched domain filter

  # Username / path contains brand-like token
  try:
    parsed = urllib.parse.urlparse(url)
    path = (parsed.path or "").lower()
    if biz and biz in path:
      score += 0.4
  except Exception:
    pass

  # Snippet mentions business name
  if biz and biz in snippet.lower():
    score += 0.2

  # Clamp
  if score > 1.0:
    score = 1.0
  return round(score, 3)


def discover_platform_handles(
  message: str,
  requested_platforms: Optional[List[str]] = None
) -> Tuple[List[PlatformResult], Dict[str, List[Tuple[str, str]]]]:
  platforms = requested_platforms or infer_platforms_from_message(message)
  # If nothing inferred/selected, return empty.
  if not platforms:
    return [], {}

  # Try to extract a business URL from the message (to use both for name and on-site links).
  url_match = re.search(r"https?://[^\s]+", message)
  business_url = url_match.group(0) if url_match else ""

  business = extract_business_name(message)
  results: List[PlatformResult] = []
  debug_search_results: Dict[str, List[Tuple[str, str]]] = {}

  # First pass: try to discover platform links directly on the business website.
  site_links = discover_links_on_site(business_url) if business_url else {k: [] for k in PLATFORM_DOMAINS.keys()}

  for platform in platforms:
    if platform not in PLATFORM_DOMAINS:
      continue
    # 1) Prefer a link found directly on the business website.
    direct_links = site_links.get(platform) or []
    if direct_links:
      # Use the first unique link as high-confidence.
      results.append(
        PlatformResult(
          platform=platform,
          url=direct_links[0],
          confidence=0.9,
          reason="Found directly on the business website HTML.",
        )
      )
      continue

    # 2) Fallback to Google search.
    try:
      search_results = google_search(business, platform, limit=5)
    except Exception as e:
      results.append(
        PlatformResult(
          platform=platform,
          url="",
          confidence=0.0,
          reason=f"Google search failed: {e}",
        )
      )
      continue

    debug_search_results[platform] = search_results

    if not search_results:
      results.append(
        PlatformResult(
          platform=platform,
          url="",
          confidence=0.0,
          reason=f"No {platform} results found for '{business}'.",
        )
      )
      continue

    # Pick the top-scoring candidate
    best_url = ""
    best_score = 0.0
    best_reason = ""
    for url, snippet in search_results:
      score = score_candidate(business, platform, url, snippet)
      if score > best_score:
        best_score = score
        best_url = url
        best_reason = snippet or "Top search result"

    # For Instagram, normalize URLs like
    #   https://www.instagram.com/pwcuriousjr/reels/?...
    # to the canonical profile URL:
    #   https://www.instagram.com/pwcuriousjr/
    if best_url and platform == "instagram":
      try:
        parsed = urllib.parse.urlparse(best_url)
        segments = [seg for seg in parsed.path.split("/") if seg]
        if segments:
          handle = segments[0]
          best_url = f"https://www.instagram.com/{handle}/"
      except Exception:
        # If normalization fails, keep original best_url
        pass

    results.append(
      PlatformResult(
        platform=platform,
        url=best_url,
        confidence=best_score,
        reason=best_reason or "Top search result",
      )
    )

  return results, debug_search_results


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  message = str(payload.get("message") or "").strip()
  args = payload.get("args") or {}
  platforms_raw = str(args.get("platforms") or "").strip()

  requested_platforms: Optional[List[str]] = None
  if platforms_raw:
    requested_platforms = [p.strip().lower() for p in platforms_raw.split(",") if p.strip()]

  if not message:
    out: Dict[str, Any] = {
      "text": "find-platform-handles: missing user message.",
      "error": "missing_message",
    }
    print(json.dumps(out))
    return

  t0 = time.time()
  handles, debug_search = discover_platform_handles(message, requested_platforms)
  elapsed = round(time.time() - t0, 2)

  # Minimise payload: only expose platform + canonical URL for each discovered handle.
  platforms_data = [
    {"platform": h.platform, "url": h.url}
    for h in handles
    if h.url
  ]

  # Human-readable text for logs and frontend skill section (outputSummary)
  text_lines = [f"{p['platform']}: {p['url']}" for p in platforms_data] if platforms_data else ["No platforms found."]
  text = "\n".join(text_lines)

  out: Dict[str, Any] = {
    "text": text,
    "data": {"platforms": platforms_data},
  }
  print(json.dumps(out))


if __name__ == "__main__":
  main()

