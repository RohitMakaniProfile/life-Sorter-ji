#!/usr/bin/env python3
"""
platform-taxonomy

Creates a dynamic platform taxonomy using Gemini (LLM) from:
- landing page URL + summary
- web-search results (urls/snippets)

Output is structured JSON used by classify-links.
"""

import json
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional

import requests


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def _safe_text(s: str) -> str:
  return " ".join((s or "").split()).strip()


def _extract_urls(text: str) -> List[str]:
  if not text:
    return []
  urls = URL_RE.findall(text)
  out: List[str] = []
  seen = set()
  for u in urls:
    u2 = u.strip().rstrip(").,]")
    if not u2 or u2 in seen:
      continue
    seen.add(u2)
    out.append(u2)
  return out


def _domain(url: str) -> str:
  try:
    return urllib.parse.urlparse(url).netloc.lower()
  except Exception:
    return ""


def _openrouter_model_candidates(model_id: str) -> List[str]:
  raw = (model_id or "").strip()
  if not raw:
    return []
  # If already namespaced (e.g. google/gemini-...), treat as OpenRouter id.
  if "/" in raw:
    return [raw]
  prefix = os.getenv("OPENROUTER_GEMINI_MODEL_PREFIX", "google/")
  prefix = (prefix or "google/").strip().rstrip("/") + "/"
  candidate = f"{prefix}{raw}"
  if candidate == raw:
    return [raw]
  return [candidate, raw]


def _openrouter_generate_json(prompt: str, model_id: str) -> Dict[str, Any]:
  api_key = os.getenv("OPENROUTER_API_KEY")
  if not api_key:
    raise RuntimeError("OPENROUTER_API_KEY is not set")

  candidates = _openrouter_model_candidates(model_id)
  if not candidates:
    raise RuntimeError("No OpenRouter model candidates resolved")

  endpoint = "https://openrouter.ai/api/v1/chat/completions"
  headers = {
    "Authorization": f"Bearer {api_key.strip()}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://ikshan.ai",
    "X-Title": "Ikshan Unified LLM",
  }

  last_exc: Optional[Exception] = None
  for model in candidates:
    try:
      payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000,
      }
      resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
      if resp.status_code == 404:
        continue
      resp.raise_for_status()
      data = resp.json()
      content = (
        data.get("choices", [{}])[0]
          .get("message", {})
          .get("content", "")
      )
      text = (content or "").strip()
      m = re.search(r"\{[\s\S]*\}", text)
      if not m:
        raise RuntimeError(f"OpenRouter returned no JSON object (model={model})")
      return json.loads(m.group(0))
    except Exception as e:
      last_exc = e
      continue

  if last_exc:
    raise last_exc
  raise RuntimeError("OpenRouter taxonomy generation failed")


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  business_url = _safe_text(args.get("businessUrl") or "")
  business_summary = _safe_text(args.get("businessSummary") or "")
  region_hint = _safe_text(args.get("regionHint") or "")
  search_results_json = args.get("searchResultsJson")

  # best-effort: allow the user message to carry JSON blocks/urls
  msg = payload.get("message", "") or ""
  if not business_url:
    urls = _extract_urls(msg)
    business_url = urls[0] if urls else ""

  # Parse search results if provided
  search_results: Dict[str, Any] = {}
  if isinstance(search_results_json, str) and search_results_json.strip():
    try:
      search_results = json.loads(search_results_json)
    except Exception:
      search_results = {}

  results = search_results.get("results") if isinstance(search_results, dict) else None
  if not isinstance(results, list):
    results = []

  # Build a compact list of candidate domains from search + message
  candidate_urls: List[str] = []
  for r in results[:15]:
    if isinstance(r, dict) and isinstance(r.get("url"), str):
      candidate_urls.append(r["url"])
  candidate_urls.extend(_extract_urls(msg))
  candidate_domains = []
  seen = set()
  for u in candidate_urls:
    d = _domain(u)
    if not d:
      continue
    if d in seen:
      continue
    seen.add(d)
    candidate_domains.append(d)
    if len(candidate_domains) >= 30:
      break

  # Backwards-compatible: keep the existing env var name, but resolve it to an OpenRouter model id.
  model = os.getenv("GEMINI_TAXONOMY_MODEL") or "gemini-2.5-flash"

  prompt = "\n".join([
    "You are building a platform taxonomy for a business analysis agent.",
    "Goal: create dynamic platform categories for THIS business/region so later we can classify discovered links without hardcoding country-specific ecosystems.",
    "",
    "Output JSON only with this shape:",
    "{",
    '  "macroTypes": ["maps","reviews","delivery","booking","marketplace","social","appstore","forums","news","jobs","payments","other"],',
    '  "categories": [',
    '    { "id": "slug", "label": "Human label", "macroType": "reviews|delivery|...", "exampleDomains": ["example.com","foo.bar"] }',
    "  ],",
    '  "domainRules": [',
    '    { "domainContains": "tripadvisor.", "categoryId": "tripadvisor_reviews" }',
    "  ]",
    "}",
    "",
    "Rules:",
    "- categories should be stable + reusable; use platform names or domain-based slugs (e.g. dianping_reviews, meituan_delivery).",
    "- categories MUST reference domains seen in candidateDomains or searchResults where possible.",
    "- If regionHint suggests China (cn) include relevant likely platforms if present in candidates; otherwise do NOT hallucinate.",
    "- Keep categories limited to what is relevant: prefer 8-20 categories, not 200.",
    "",
    f"businessUrl: {business_url or '(unknown)'}",
    f"regionHint: {region_hint or '(none)'}",
    "",
    "businessSummary (may be empty):",
    business_summary[:2000] if business_summary else "(none)",
    "",
    "candidateDomains (from search + provided text):",
    json.dumps(candidate_domains, ensure_ascii=False),
    "",
    "searchResults (top 8):",
    json.dumps(results[:8], ensure_ascii=False)[:12000],
  ])

  try:
    taxonomy = _openrouter_generate_json(prompt, model_id=model)
  except Exception as e:
    # fallback: minimal taxonomy using domains only
    taxonomy = {
      "macroTypes": ["maps","reviews","delivery","booking","marketplace","social","appstore","forums","news","jobs","payments","other"],
      "categories": [],
      "domainRules": [{"domainContains": d, "categoryId": "other"} for d in candidate_domains[:10]],
      "error": f"taxonomy_llm_failed: {e}"
    }

  out = {
    # Runner should be a raw structured producer. Natural language summary is generated in loader.ts.
    "text": "",
    "data": {
      "model": model,
      "businessUrl": business_url,
      "regionHint": region_hint,
      "candidateDomains": candidate_domains,
      "taxonomy": taxonomy,
    },
  }
  print(json.dumps(out))


if __name__ == "__main__":
  main()

