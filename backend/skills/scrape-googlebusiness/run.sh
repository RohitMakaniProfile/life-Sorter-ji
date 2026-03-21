#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --business-name "CuriousJr" --location "India"

BUSINESS_NAME=""
LOCATION_HINT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --business-name) BUSINESS_NAME="$2"; shift 2 ;;
    --location) LOCATION_HINT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$BUSINESS_NAME" ]]; then
  echo "scrape-googlebusiness: --business-name is required" >&2
  exit 1
fi

PAYLOAD=$(jq -n \
  --arg businessName "$BUSINESS_NAME" \
  --arg locationHint "$LOCATION_HINT" \
  '{ args: { businessName: $businessName, locationHint: ($locationHint | select(. != "")) } }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

