#!/usr/bin/env python3
import sys
import json
from typing import Any, Dict


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  message = payload.get("message", "")

  text = (
    "Google Business scraping skill is wired but not fully implemented yet.\n\n"
    f"Prompt: {message}\n\n"
    "Implement: find the correct Google Business / Maps profile for the brand, scrape "
    "key fields (ratings, review count, recent review snippets), and summarize presence."
  )

  out: Dict[str, Any] = {"text": text}
  print(json.dumps(out))


if __name__ == "__main__":
  main()

