#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer repo-local venv if present.
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PY="$ROOT_DIR/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

PORT="${PORT:-8000}"
"$PY" -m uvicorn app.main:app --reload --port "$PORT"
