#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --url "https://www.curiousjr.com" --instructions "Click pricing, then plans"

URL=""
INSTRUCTIONS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --instructions) INSTRUCTIONS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$URL" ]]; then
  echo "scrape-agentbrowser: --url is required" >&2
  exit 1
fi

PAYLOAD=$(jq -n \
  --arg url "$URL" \
  --arg instructions "$INSTRUCTIONS" \
  '{ args: { url: $url, instructions: ($instructions | select(. != "")) } }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

