#!/usr/bin/env bash
set -euo pipefail

URL="${1:-}"
if [[ -z "${URL}" ]]; then
  echo "Usage: ./run.sh \"https://example.com\""
  exit 1
fi

python3 runner.py <<EOF
{"message":"${URL}","args":{"url":"${URL}"}}
EOF

