#!/usr/bin/env python3
import sys
import json
import os
import subprocess
import tempfile
from typing import Any, Dict


HERE = os.path.dirname(os.path.abspath(__file__))
QUORA_SCRIPT = os.path.join(HERE, "scripts", "quora_scraper.py")


def main() -> None:
  raw = sys.stdin.read()
  try:
    payload = json.loads(raw) if raw.strip() else {}
  except Exception:
    payload = {}

  args = payload.get("args") or {}
  target = args.get("query") or payload.get("message", "").strip()

  if not target:
    out: Dict[str, Any] = {"text": "quora-search: missing query or target", "error": "missing_target"}
    print(json.dumps(out))
    return

  with tempfile.TemporaryDirectory() as tmpdir:
    output_path = os.path.join(tmpdir, "quora.json")
    cmd = [
      sys.executable,
      QUORA_SCRIPT,
      "--target", target,
      "--output", output_path,
    ]

    try:
      proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
      if proc.returncode != 0:
        out: Dict[str, Any] = {
          "text": f"quora-search failed with code {proc.returncode}. stderr:\n{proc.stderr[:2000]}",
          "error": "quora_scraper_failed",
        }
        print(json.dumps(out))
        return

      with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception as e:
      out = {
        "text": f"quora-search: error running scraper or reading output: {e}",
        "error": "quora_error",
      }
      print(json.dumps(out))
      return

  questions = data.get("questions", [])

  summary_lines = [
    "Quora discussion snapshot",
    "",
    f"- Questions scraped: {len(questions)}",
  ]

  text = "\n".join(summary_lines)

  out: Dict[str, Any] = {"text": text, "data": data}
  print(json.dumps(out))


if __name__ == "__main__":
  main()

