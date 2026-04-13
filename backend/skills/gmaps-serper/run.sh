#!/usr/bin/env bash
set -euo pipefail

QUERY="${1:-}"
if [[ -z "${QUERY}" ]]; then
  echo "Usage: ./run.sh \"business name or google maps url\""
  exit 1
fi

LOCATION="${2:-}"

python3 runner.py <<EOF
{"message":"${QUERY}","args":{"query":"${QUERY}","location":"${LOCATION}","gl":"in","num":5}}
EOF

