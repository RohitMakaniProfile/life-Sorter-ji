#!/usr/bin/env python3
import sys
import json
import os
import subprocess
import tempfile
from typing import Any, Dict


HERE = os.path.dirname(os.path.abspath(__file__))
BS4_SCRIPT = os.path.join(HERE, "scripts", "bs4_scraper.py")


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  url = args.get("url") or payload.get("message", "").strip()
  max_pages = int(args.get("maxPages") or 30)
  max_depth = int(args.get("maxDepth") or 4)

  if not url:
    out: Dict[str, Any] = {"text": "scrape-bs4: missing url in args.url or message", "error": "missing_url"}
    print(json.dumps(out))
    return

  with tempfile.TemporaryDirectory() as tmpdir:
    output_path = os.path.join(tmpdir, "bs4.json")
    cmd = [
      sys.executable,
      BS4_SCRIPT,
      "--url", url,
      "--output", output_path,
      "--max-pages", str(max_pages),
      "--max-depth", str(max_depth),
    ]

    try:
      proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
      if proc.returncode != 0:
        out: Dict[str, Any] = {
          "text": f"scrape-bs4 failed with code {proc.returncode}. stderr:\n{proc.stderr[:2000]}",
          "error": "bs4_scraper_failed",
        }
        print(json.dumps(out))
        return

      try:
        with open(output_path, "r", encoding="utf-8") as f:
          data = json.load(f)
      except Exception as e:
        out = {
          "text": f"scrape-bs4: crawler completed but output JSON could not be read: {e}",
          "error": "output_read_error",
        }
        print(json.dumps(out))
        return

      pages = data.get("pages", [])
      base_url = data.get("base_url", url)
      stats = data.get("stats", {})
      # Build user-facing text from actual scraped content (title + body_text per page)
      parts = [
        f"Website snapshot (bs4 crawler)\n",
        f"Base URL: {base_url}",
        f"Pages scraped: {stats.get('total_pages', len(pages))}\n",
      ]
      max_body_per_page = 15000
      for i, p in enumerate(pages):
        page_url = p.get("url", "")
        title = (p.get("title") or "").strip()
        body = (p.get("body_text") or "").strip()
        if len(body) > max_body_per_page:
          body = body[:max_body_per_page] + "\n[... truncated ...]"
        parts.append(f"---\nPage {i + 1}: {page_url}")
        if title:
          parts.append(f"Title: {title}")
        if body:
          parts.append(body)
        parts.append("")
      summary = "\n".join(parts).strip()

      out = {
        "text": summary,
        "data": data,
      }
      print(json.dumps(out))
    except Exception as e:
      out = {"text": f"scrape-bs4 error: {e}", "error": "run_error"}
      print(json.dumps(out))


if __name__ == "__main__":
  main()

