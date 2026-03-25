#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --channel-url "https://www.youtube.com/@curiousjr" --max-videos 5
#   ./run.sh --video-url "https://www.youtube.com/watch?v=XXXX"
#   ./run.sh --query "curiousjr reviews" --no-fetch-comments

CHANNEL_URL=""
VIDEO_URL=""
QUERY=""
MAX_VIDEOS=5
FETCH_COMMENTS=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --channel-url) CHANNEL_URL="$2"; shift 2 ;;
    --video-url) VIDEO_URL="$2"; shift 2 ;;
    --query) QUERY="$2"; shift 2 ;;
    --max-videos) MAX_VIDEOS="$2"; shift 2 ;;
    --no-fetch-comments) FETCH_COMMENTS=false; shift 1 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

PAYLOAD=$(jq -n \
  --arg channelUrl "$CHANNEL_URL" \
  --arg videoUrl "$VIDEO_URL" \
  --arg query "$QUERY" \
  --argjson maxVideos "$MAX_VIDEOS" \
  --arg fetchDetails "$FETCH_COMMENTS" \
  '{
    args: (
      { maxVideos: $maxVideos, fetchDetails: ($fetchDetails == "true") }
      + (if $channelUrl != "" then { channelUrl: $channelUrl } else {} end)
      + (if $videoUrl != "" then { videoUrl: $videoUrl } else {} end)
      + (if $query != "" then { query: $query } else {} end)
    )
  }')

python3 "$(dirname "$0")/runner.py" <<<"$PAYLOAD"

