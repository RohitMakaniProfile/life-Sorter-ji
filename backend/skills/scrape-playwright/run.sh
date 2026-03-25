#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --url "https://www.curiousjr.com"
#   ./run.sh --url "https://www.curiousjr.com" --max-pages 20
#   ./run.sh --url "https://www.curiousjr.com" --deep   # full-site crawl (default)

URL=""
MAX_PAGES=9999
DEEP="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --max-pages) MAX_PAGES="$2"; shift 2 ;;
    --deep) DEEP="true"; shift 1 ;;
    --no-deep) DEEP="false"; shift 1 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$URL" ]]; then
  echo "scrape-playwright: --url is required" >&2
  exit 1
fi

# jq --argjson needs JSON literals true/false, not strings
DEEP_JSON=true
[[ "$DEEP" == "false" ]] && DEEP_JSON=false

PAYLOAD=$(jq -n \
  --arg url "$URL" \
  --argjson maxPages "$MAX_PAGES" \
  --argjson deep "$DEEP_JSON" \
  '{ args: { url: $url, maxPages: $maxPages, deep: $deep } }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

