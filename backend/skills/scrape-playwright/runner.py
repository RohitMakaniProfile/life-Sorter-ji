#!/usr/bin/env python3
"""
Runner for scrape-playwright. Streams progress from the scraper to the backend:
- Scraper (playwright_scraper.py) writes one JSON object per line to stderr:
  {"event": "started"} | {"event": "page", "url": "...", "status": "scraping"|"done"|"failed", "error": "..."}
- This runner reads stderr line-by-line and prints each line to stdout with prefix "PROGRESS:"
- The Node loader reads runner stdout, parses PROGRESS lines, and calls onProgress(meta) for streaming to frontend.
"""
import sys
import json
import os
import subprocess
import threading
from typing import Any, Dict


HERE = os.path.dirname(os.path.abspath(__file__))
PW_SCRIPT = os.path.join(HERE, "scripts", "playwright_scraper.py")


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  url = args.get("url") or payload.get("message", "").strip()
  # Default to full-site crawl (all pages); single-page scrape is never used when invoked by the agent
  max_pages = int(args.get("maxPages") if args.get("maxPages") is not None else 9999)
  max_depth = int(args.get("maxDepth") if args.get("maxDepth") is not None else 10)
  deep = bool(args["deep"]) if "deep" in args and args["deep"] is not None else True
  parallel = bool(args["parallel"]) if "parallel" in args and args["parallel"] is not None else False

  if not url:
    out: Dict[str, Any] = {"text": "scrape-playwright: missing url in args.url or message", "error": "missing_url"}
    print(json.dumps(out))
    return

  cmd = [
    sys.executable,
    "-u",
    PW_SCRIPT,
    "--url", url,
    "--max-pages", str(max_pages),
    "--max-depth", str(max_depth),
  ]
  if deep:
    cmd.append("--deep")
  if parallel:
    cmd.append("--parallel")
  else:
    cmd.append("--no-parallel")

  try:
    proc = subprocess.Popen(
      cmd,
      stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
      bufsize=1,
    )

    stdout_lines = []

    def stream_stderr():
      for line in proc.stderr:
        line = line.rstrip("\n")
        if line.strip():
          print("PROGRESS:" + line, flush=True)

    def collect_stdout():
      for line in proc.stdout:
        stdout_lines.append(line)

    t_err = threading.Thread(target=stream_stderr)
    t_out = threading.Thread(target=collect_stdout)
    t_err.daemon = True
    t_out.daemon = True
    t_err.start()
    t_out.start()

    proc.wait()
    t_err.join(timeout=1)
    t_out.join(timeout=1)

    if proc.returncode != 0:
      out = {
        "text": f"scrape-playwright failed with code {proc.returncode}. Check progress for details.",
        "error": "playwright_scraper_failed",
      }
      print(json.dumps(out))
      return

    # Final result is the last non-empty line on stdout (scraper prints one JSON object)
    raw_stdout = "".join(stdout_lines)
    final_line = raw_stdout.strip().split("\n")[-1].strip() if raw_stdout.strip() else "{}"
    try:
      data = json.loads(final_line)
    except json.JSONDecodeError:
      out = {
        "text": "scrape-playwright: could not parse scraper result",
        "error": "playwright_parse_error",
      }
      print(json.dumps(out))
      return
  except Exception as e:
    out = {
      "text": f"scrape-playwright: error running scraper or reading output: {e}",
      "error": "playwright_error",
    }
    print(json.dumps(out))
    return

  base_url = data.get("base_url", url)
  scraped_urls = data.get("scraped_urls", [])
  n = len(scraped_urls)
  text = f"Playwright scrape for {base_url} — {n} page(s) scraped. Full content was streamed via progress and stored in the skill call output."

  out = {"text": text, "data": data}
  print(json.dumps(out))


if __name__ == "__main__":
  main()


