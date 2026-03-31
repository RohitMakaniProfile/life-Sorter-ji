#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

uvicorn app.main:app --reload --host "$HOST" --port "$PORT"
