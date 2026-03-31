#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

PORT="${PORT:-8081}"
HOST="${HOST:-0.0.0.0}"

if [[ -f "$ROOT_DIR/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi

python -m uvicorn app.main:app --app-dir "$ROOT_DIR/app" --reload --host "$HOST" --port "$PORT"

