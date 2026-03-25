#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --app-id com.whatsapp --country US

APP_ID=""
COUNTRY="in"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-id) APP_ID="$2"; shift 2 ;;
    --country) COUNTRY="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$APP_ID" ]]; then
  echo "playstore-sentiment: --app-id is required" >&2
  exit 1
fi

PAYLOAD=$(jq -n \
  --arg appId "$APP_ID" \
  --arg country "$COUNTRY" \
  '{ args: { appId: $appId, country: $country } }')

python3 -u "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

