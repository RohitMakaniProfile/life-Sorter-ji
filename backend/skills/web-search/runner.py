#!/usr/bin/env python3
"""
web-search: generic web search skill.

Implementation: prefers Serper.dev JSON API (requires SERPER_API_KEY), with an optional
fallback to DuckDuckGo HTML results when no API key is present.
This is a pragmatic baseline for discovery (presence links, competitors, funding/news).

Input (stdin JSON):
{
  "message": "<user message>",
  "args": { "query": "...", "maxResults": 10 }
}

Output (stdout JSON):
{
  "text": "<short summary>",
  "data": {
    "query": "...",
    "results": [{ "title": "...", "url": "...", "snippet": "..." }]
  }
}
"""

import json
import os
import sys
import urllib.parse
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup


UA = (
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def _safe_text(s: str) -> str:
  return " ".join((s or "").split()).strip()

def serper_search(query: str, max_results: int = 10, timeout: float = 15.0) -> List[Dict[str, str]]:
  """
  Serper.dev Google Search API.
  Docs: https://serper.dev/
  Returns list of {title,url,snippet}.
  """
  api_key = os.environ.get("SERPER_API_KEY") or os.environ.get("GOOGLE_SERPER_API_KEY")
  if not api_key:
    raise RuntimeError("SERPER_API_KEY is not set")

  gl = (os.environ.get("SERPER_GL") or "").strip() or None
  hl = (os.environ.get("SERPER_HL") or "").strip() or None

  resp = requests.post(
    "https://google.serper.dev/search",
    headers={
      "X-API-KEY": api_key,
      "Content-Type": "application/json",
    },
    json={
      "q": query,
      "num": max_results,
      **({"gl": gl} if gl else {}),
      **({"hl": hl} if hl else {}),
    },
    timeout=timeout,
  )
  resp.raise_for_status()
  data = resp.json() if resp.text else {}

  organic = data.get("organic") or []
  out: List[Dict[str, str]] = []
  for item in organic:
    title = _safe_text(str(item.get("title") or ""))
    url = str(item.get("link") or "").strip()
    snippet = _safe_text(str(item.get("snippet") or ""))
    if not url or not title:
      continue
    out.append({"title": title, "url": url, "snippet": snippet})
    if len(out) >= max_results:
      break
  return out

def ddg_search(query: str, max_results: int = 10, timeout: float = 15.0) -> List[Dict[str, str]]:
  url = "https://duckduckgo.com/html/"
  params = {"q": query}
  resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=timeout)
  resp.raise_for_status()

  soup = BeautifulSoup(resp.text, "html.parser")
  out: List[Dict[str, str]] = []

  # DDG HTML results typically use .result__a and .result__snippet
  for res in soup.select(".result"):
    a = res.select_one("a.result__a")
    if not a:
      continue
    title = _safe_text(a.get_text())
    href = a.get("href") or ""
    if not href:
      continue

    # DDG sometimes uses redirect links; attempt to unwrap if present
    parsed = urllib.parse.urlparse(href)
    q = urllib.parse.parse_qs(parsed.query)
    if "uddg" in q and q["uddg"]:
      href = q["uddg"][0]

    snippet_el = res.select_one(".result__snippet")
    snippet = _safe_text(snippet_el.get_text() if snippet_el else "")

    out.append({"title": title, "url": href, "snippet": snippet})
    if len(out) >= max_results:
      break

  # Fallback: try generic anchors if the page structure changes
  if not out:
    for a in soup.find_all("a"):
      href = a.get("href") or ""
      title = _safe_text(a.get_text())
      if not href.startswith("http"):
        continue
      if not title or len(title) < 3:
        continue
      out.append({"title": title, "url": href, "snippet": ""})
      if len(out) >= max_results:
        break

  return out

def _split_queries(s: str) -> List[str]:
  if not s:
    return []
  parts = [p.strip() for p in s.split("\n")]
  out: List[str] = []
  seen = set()
  for p in parts:
    if not p:
      continue
    if p in seen:
      continue
    seen.add(p)
    out.append(p)
  return out

def _dedupe_results(results_by_query: List[Tuple[str, List[Dict[str, str]]]], max_total: int) -> List[Dict[str, str]]:
  out: List[Dict[str, str]] = []
  seen = set()
  for q, items in results_by_query:
    for r in items:
      url = (r.get("url") or "").strip()
      if not url or url in seen:
        continue
      seen.add(url)
      out.append({**r, "sourceQuery": q})
      if len(out) >= max_total:
        return out
  return out

def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  query = (args.get("query") or "").strip()
  queries_blob = (args.get("queries") or "").strip()
  if not query and not queries_blob:
    # fallback to message for single query mode
    query = (payload.get("message") or "").strip()

  max_results = args.get("maxResults") or args.get("max_results") or 10
  max_results_per_query = args.get("maxResultsPerQuery") or args.get("max_results_per_query") or 6
  max_total_results = args.get("maxTotalResults") or args.get("max_total_results") or 40
  try:
    max_results = int(max_results)
  except Exception:
    max_results = 10
  try:
    max_results_per_query = int(max_results_per_query)
  except Exception:
    max_results_per_query = 6
  try:
    max_total_results = int(max_total_results)
  except Exception:
    max_total_results = 40
  if max_results <= 0:
    max_results = 10
  if max_results > 25:
    max_results = 25
  if max_results_per_query <= 0:
    max_results_per_query = 6
  if max_results_per_query > 15:
    max_results_per_query = 15
  if max_total_results <= 0:
    max_total_results = 40
  if max_total_results > 120:
    max_total_results = 120

  queries = _split_queries(queries_blob)
  if not queries and query:
    queries = [query]
  if not queries:
    print(json.dumps({"text": "web-search: missing query/queries", "error": "missing_query"}))
    return

  results_by_query: List[Tuple[str, List[Dict[str, str]]]] = []
  errors: List[str] = []
  used_provider = "serper" if (os.environ.get("SERPER_API_KEY") or os.environ.get("GOOGLE_SERPER_API_KEY")) else "ddg-html"
  for q in queries[:20]:
    try:
      per_limit = max_results_per_query if len(queries) > 1 else max_results
      if used_provider == "serper":
        per = serper_search(q, max_results=per_limit)
      else:
        per = ddg_search(q, max_results=per_limit)
      results_by_query.append((q, per))
    except Exception as e:
      errors.append(f"{q}: {str(e)[:160]}")
      results_by_query.append((q, []))

  combined = _dedupe_results(results_by_query, max_total=max_total_results)

  summary_lines = [
    "Web search (batch)",
    f"- Provider: {used_provider}",
    f"- Queries: {len(queries)}",
    f"- Unique results: {len(combined)}",
  ]
  if errors:
    summary_lines.append(f"- Query errors: {len(errors)}")
  summary = "\n".join(summary_lines)

  out: Dict[str, Any] = {
    "text": summary,
    "data": {
      "provider": used_provider,
      "queries": queries,
      "resultsByQuery": [
        {"query": q, "results": items, "count": len(items)} for (q, items) in results_by_query
      ],
      "results": combined,
      "errors": errors,
    },
  }
  print(json.dumps(out))


if __name__ == "__main__":
  main()

