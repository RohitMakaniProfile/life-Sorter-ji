#!/usr/bin/env python3
import sys
import json
import os
import subprocess
import tempfile
from typing import Any, Dict


HERE = os.path.dirname(os.path.abspath(__file__))
IG_SCRIPT = os.path.join(HERE, "scripts", "instagram_scraper.py")


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  target = args.get("handle") or args.get("postUrl") or payload.get("message", "").strip()
  max_posts = int(args.get("maxPosts") or 5)

  if not target:
    out: Dict[str, Any] = {"text": "instagram-sentiment: missing handle or target", "error": "missing_target"}
    print(json.dumps(out))
    return

  with tempfile.TemporaryDirectory() as tmpdir:
    output_path = os.path.join(tmpdir, "instagram.json")
    cmd = [
      sys.executable,
      IG_SCRIPT,
      "--target", target,
      "--output", output_path,
      "--max-posts", str(max_posts),
    ]

    try:
      proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
      if proc.returncode != 0:
        out: Dict[str, Any] = {
          "text": f"instagram-sentiment failed with code {proc.returncode}. stderr:\n{proc.stderr[:2000]}",
          "error": "instagram_scraper_failed",
        }
        print(json.dumps(out))
        return

      with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception as e:
      out = {
        "text": f"instagram-sentiment: error running scraper or reading output: {e}",
        "error": "instagram_error",
      }
      print(json.dumps(out))
      return

  posts = data.get("posts", [])
  total_comments = data.get("total_comments", 0)
  username = data.get("username") or target
  note = data.get("note")

  summary_lines = [
    f"Instagram sentiment snapshot for @{username}",
    "",
    f"- Posts scraped: {len(posts)}",
    f"- Total comments: {total_comments}",
  ]
  if note:
    summary_lines.append(f"- Note: {note}")

  text = "\n".join(summary_lines)

  out: Dict[str, Any] = {"text": text, "data": data}
  print(json.dumps(out))


if __name__ == "__main__":
  main()


