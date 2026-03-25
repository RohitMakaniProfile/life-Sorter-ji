#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --handle curiousjr --max-posts 5
#   ./run.sh --post-url "https://www.instagram.com/p/XXXX/"
#
# Flags:
#   --handle     Instagram handle or profile URL
#   --post-url   Specific post URL (optional)
#   --brand      Brand or product name (optional, for context only)
#   --max-posts  Max posts to scrape (default: 5)

HANDLE=""
POST_URL=""
BRAND=""
MAX_POSTS=5

while [[ $# -gt 0 ]]; do
  case "$1" in
    --handle) HANDLE="$2"; shift 2 ;;
    --post-url) POST_URL="$2"; shift 2 ;;
    --brand) BRAND="$2"; shift 2 ;;
    --max-posts) MAX_POSTS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

PAYLOAD=$(jq -n \
  --arg handle "$HANDLE" \
  --arg postUrl "$POST_URL" \
  --arg brand "$BRAND" \
  --argjson maxPosts "$MAX_POSTS" \
  '{
    args: (
      { maxPosts: $maxPosts }
      + (if $handle != "" then { handle: $handle } else {} end)
      + (if $postUrl != "" then { postUrl: $postUrl } else {} end)
      + (if $brand != "" then { brand: $brand } else {} end)
    )
  }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

