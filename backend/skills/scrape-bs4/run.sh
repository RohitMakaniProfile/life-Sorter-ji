#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --url "https://www.curiousjr.com" --max-pages 80 --max-depth 3

URL=""
MAX_PAGES=80
MAX_DEPTH=3

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --max-pages) MAX_PAGES="$2"; shift 2 ;;
    --max-depth) MAX_DEPTH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$URL" ]]; then
  echo "scrape-bs4: --url is required" >&2
  exit 1
fi

PAYLOAD=$(jq -n \
  --arg url "$URL" \
  --argjson maxPages "$MAX_PAGES" \
  --argjson maxDepth "$MAX_DEPTH" \
  '{ args: { url: $url, maxPages: $maxPages, maxDepth: $maxDepth } }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

