#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --url "https://example.com"
#   ./run.sh --url "https://example.com" --max-pages 20
#   ./run.sh --url "https://example.com" --deep    # full-site style (default)
#   ./run.sh --url "https://endee.io" --one-page   # single URL; includes tech_stack in page_data (stderr)
#
# Prefer this script over backend/run.sh — backend/run.sh is only for the FastAPI server.
#
# Browsers: pip does not install Chromium. This script runs `python -m playwright install chromium`
# automatically (quick no-op when already present). Set SKIP_PLAYWRIGHT_INSTALL=1 to skip.

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"
if [[ -x "$BACKEND_ROOT/.venv/bin/python" ]]; then
  PY="$BACKEND_ROOT/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

URL=""
MAX_PAGES=9999
MAX_DEPTH=10
DEEP="true"
PARALLEL="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --max-pages) MAX_PAGES="$2"; shift 2 ;;
    --max-depth) MAX_DEPTH="$2"; shift 2 ;;
    --deep) DEEP="true"; shift 1 ;;
    --no-deep) DEEP="false"; shift 1 ;;
    --one-page) MAX_PAGES=1; MAX_DEPTH=0; DEEP="false"; shift 1 ;;
    --parallel) PARALLEL="true"; shift 1 ;;
    --no-parallel) PARALLEL="false"; shift 1 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$URL" ]]; then
  echo "scrape-playwright: --url is required" >&2
  exit 1
fi

if [[ "${SKIP_PLAYWRIGHT_INSTALL:-0}" != "1" ]]; then
  "$PY" -m playwright install chromium
fi

DEEP_JSON=true
[[ "$DEEP" == "false" ]] && DEEP_JSON=false

PARALLEL_JSON=false
[[ "$PARALLEL" == "true" ]] && PARALLEL_JSON=true

PAYLOAD=$(jq -n \
  --arg url "$URL" \
  --argjson maxPages "$MAX_PAGES" \
  --argjson maxDepth "$MAX_DEPTH" \
  --argjson deep "$DEEP_JSON" \
  --argjson parallel "$PARALLEL_JSON" \
  '{ args: { url: $url, maxPages: $maxPages, maxDepth: $maxDepth, deep: $deep, parallel: $parallel } }')

exec "$PY" -u "$SKILL_DIR/runner.py" <<<"$PAYLOAD"
</think>


<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
Read