#!/usr/bin/env python3
import sys
import json
import os
import subprocess
import tempfile
from typing import Any, Dict


HERE = os.path.dirname(os.path.abspath(__file__))
YT_SCRIPT = os.path.join(HERE, "scripts", "youtube_scraper.py")


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  target = args.get("channelUrl") or args.get("videoUrl") or args.get("query") or payload.get("message", "").strip()
  max_videos = int(args.get("maxVideos") or 5)
  fetch_details = args.get("fetchDetails", True)

  if not target:
    out: Dict[str, Any] = {"text": "youtube-sentiment: missing target (channelUrl, videoUrl, or query)", "error": "missing_target"}
    print(json.dumps(out))
    return

  with tempfile.TemporaryDirectory() as tmpdir:
    output_path = os.path.join(tmpdir, "youtube.json")
    cmd = [
      sys.executable,
      YT_SCRIPT,
      "--target", target,
      "--output", output_path,
      "--max-videos", str(max_videos),
    ]
    if not fetch_details:
      cmd.append("--no-fetch-details")

    try:
      proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
      if proc.returncode != 0:
        out: Dict[str, Any] = {
          "text": f"youtube-sentiment failed with code {proc.returncode}. stderr:\n{proc.stderr[:2000]}",
          "error": "youtube_scraper_failed",
        }
        print(json.dumps(out))
        return

      with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception as e:
      out = {
        "text": f"youtube-sentiment: error running scraper or reading output: {e}",
        "error": "youtube_error",
      }
      print(json.dumps(out))
      return

  videos = data.get("videos", [])
  total_comments = data.get("total_comments", 0)

  summary_lines = [
    "YouTube sentiment snapshot",
    "",
    f"- Videos scraped: {len(videos)}",
    f"- Total comments: {total_comments}",
  ]

  text = "\n".join(summary_lines)

  out: Dict[str, Any] = {"text": text, "data": data}
  print(json.dumps(out))


if __name__ == "__main__":
  main()

