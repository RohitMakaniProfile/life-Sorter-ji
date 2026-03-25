#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh --message "https://www.curiousjr.com do instagram analysis"
#   ./run.sh --message "Acme Corp deep analysis" --platforms "instagram,youtube,playstore"
#
# Flags:
#   --message    Free-form user message (required)
#   --platforms  Comma-separated platform ids (instagram,youtube,playstore) (optional)

MESSAGE=""
PLATFORMS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message) MESSAGE="$2"; shift 2 ;;
    --platforms) PLATFORMS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$MESSAGE" ]]; then
  echo "Usage: $0 --message \"<user message>\" [--platforms \"instagram,youtube,playstore\"]" >&2
  exit 1
fi

PY_BIN=${PYTHON_BIN:-python3}

# Build JSON payload using Python to avoid jq incompatibilities.
PAYLOAD=$(FH_MESSAGE="$MESSAGE" FH_PLATFORMS="$PLATFORMS" "$PY_BIN" - <<'PY'
import json, os
message = os.environ.get("FH_MESSAGE", "")
platforms = os.environ.get("FH_PLATFORMS", "")
payload = {"message": message}
if platforms:
    payload["args"] = {"platforms": platforms}
print(json.dumps(payload))
PY
)

echo "$PAYLOAD" | "$PY_BIN" "$(dirname "$0")/runner.py"


