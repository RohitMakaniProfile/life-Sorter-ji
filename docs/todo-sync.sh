#!/bin/bash

# ============================================
# TODO Gist Sync Script
# ============================================
# Usage:
#   ./todo-sync.sh pull   - Download from Gist to local TODO.md
#   ./todo-sync.sh push   - Upload local TODO.md to Gist
#   ./todo-sync.sh watch  - Watch for changes and auto-push
# ============================================

GIST_ID="ee92556c3f1c8d6e9b3976f771245ef3"
GIST_FILENAME="DOABLE_CLAW_TODO.md"
LOCAL_FILE="$(dirname "$0")/TODO.md"

# GitHub token - set via environment variable or edit here
# Export: export GITHUB_GIST_TOKEN="ghp_xxxx"
GITHUB_TOKEN="${GITHUB_GIST_TOKEN:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================
# PULL: Gist → Local
# ============================================
pull_from_gist() {
    echo -e "${YELLOW}📥 Pulling from Gist...${NC}"

    # Fetch gist (works without auth for public gists)
    RESPONSE=$(curl -s "https://api.github.com/gists/${GIST_ID}")

    # Check if we got valid response
    if echo "$RESPONSE" | grep -q '"message"'; then
        echo -e "${RED}❌ Error: $(echo "$RESPONSE" | grep -o '"message":"[^"]*"')${NC}"
        exit 1
    fi

    # Extract content using jq if available, otherwise use grep/sed
    if command -v jq &> /dev/null; then
        CONTENT=$(echo "$RESPONSE" | jq -r ".files[\"${GIST_FILENAME}\"].content")
    else
        # Fallback: extract content between quotes (basic parsing)
        CONTENT=$(echo "$RESPONSE" | grep -o '"content":"[^"]*"' | head -1 | sed 's/"content":"//;s/"$//' | sed 's/\\n/\n/g' | sed 's/\\"/"/g')
    fi

    if [ -z "$CONTENT" ] || [ "$CONTENT" = "null" ]; then
        echo -e "${RED}❌ Error: Could not extract content from gist${NC}"
        echo "Available files in gist:"
        echo "$RESPONSE" | grep -o '"filename":"[^"]*"'
        exit 1
    fi

    # Backup existing file
    if [ -f "$LOCAL_FILE" ]; then
        cp "$LOCAL_FILE" "${LOCAL_FILE}.bak"
    fi

    # Write content
    echo "$CONTENT" > "$LOCAL_FILE"

    echo -e "${GREEN}✅ Pulled to ${LOCAL_FILE}${NC}"
    echo "   Backup saved to ${LOCAL_FILE}.bak"
}

# ============================================
# PUSH: Local → Gist
# ============================================
push_to_gist() {
    echo -e "${YELLOW}📤 Pushing to Gist...${NC}"

    # Check token
    if [ -z "$GITHUB_TOKEN" ]; then
        echo -e "${RED}❌ Error: GITHUB_GIST_TOKEN not set${NC}"
        echo "   Set it with: export GITHUB_GIST_TOKEN='ghp_your_token_here'"
        echo "   Or edit this script and set GITHUB_TOKEN directly"
        exit 1
    fi

    # Check local file exists
    if [ ! -f "$LOCAL_FILE" ]; then
        echo -e "${RED}❌ Error: ${LOCAL_FILE} not found${NC}"
        exit 1
    fi

    # Read content and escape for JSON
    CONTENT=$(cat "$LOCAL_FILE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

    # Build JSON payload
    PAYLOAD=$(cat <<EOF
{
  "files": {
    "${GIST_FILENAME}": {
      "content": ${CONTENT}
    }
  }
}
EOF
)

    # Push to gist
    RESPONSE=$(curl -s -X PATCH \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "https://api.github.com/gists/${GIST_ID}")

    # Check response
    if echo "$RESPONSE" | grep -q '"message"'; then
        ERROR=$(echo "$RESPONSE" | grep -o '"message":"[^"]*"')
        echo -e "${RED}❌ Push failed: ${ERROR}${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ Pushed to Gist successfully${NC}"
    echo "   View at: https://gist.github.com/${GIST_ID}"
}

# ============================================
# WATCH: Auto-push on file change
# ============================================
watch_and_push() {
    echo -e "${YELLOW}👀 Watching ${LOCAL_FILE} for changes...${NC}"
    echo "   Press Ctrl+C to stop"

    # Check if inotifywait is available (Linux)
    if command -v inotifywait &> /dev/null; then
        while true; do
            inotifywait -q -e modify "$LOCAL_FILE"
            echo -e "${YELLOW}📝 File changed, pushing...${NC}"
            sleep 1  # Debounce
            push_to_gist
        done
    # Check if fswatch is available (macOS)
    elif command -v fswatch &> /dev/null; then
        fswatch -o "$LOCAL_FILE" | while read; do
            echo -e "${YELLOW}📝 File changed, pushing...${NC}"
            sleep 1  # Debounce
            push_to_gist
        done
    else
        echo -e "${RED}❌ No file watcher found${NC}"
        echo "   Install inotify-tools (Linux): sudo apt install inotify-tools"
        echo "   Install fswatch (macOS): brew install fswatch"
        exit 1
    fi
}

# ============================================
# MAIN
# ============================================
case "${1:-help}" in
    pull)
        pull_from_gist
        ;;
    push)
        push_to_gist
        ;;
    watch)
        watch_and_push
        ;;
    *)
        echo "TODO Gist Sync"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  pull   - Download from Gist to local TODO.md"
        echo "  push   - Upload local TODO.md to Gist"
        echo "  watch  - Watch for changes and auto-push"
        echo ""
        echo "Setup:"
        echo "  export GITHUB_GIST_TOKEN='ghp_your_token_here'"
        echo ""
        ;;
esac

