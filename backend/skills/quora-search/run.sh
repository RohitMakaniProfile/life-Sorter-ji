#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --query "curiousjr reviews"

QUERY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$QUERY" ]]; then
  echo "quora-search: --query is required" >&2
  exit 1
fi

PAYLOAD=$(jq -n --arg query "$QUERY" '{ args: { query: $query } }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

