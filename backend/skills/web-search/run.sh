#!/usr/bin/env bash
set -euo pipefail

QUERY="${1:-}"
if [[ -z "${QUERY}" ]]; then
  echo "Usage: ./run.sh \"query here\""
  exit 1
fi

python3 runner.py <<EOF
{"message":"${QUERY}","args":{"query":"${QUERY}","maxResults":10}}
EOF

