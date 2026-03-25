#!/usr/bin/env bash
set -euo pipefail

URLS="${1:-}"
if [[ -z "${URLS}" ]]; then
  echo "Usage: ./run.sh \"https://a.com, https://b.com\""
  exit 1
fi

python3 runner.py <<EOF
{"message":"${URLS}","args":{"urls":"${URLS}"}}
EOF

