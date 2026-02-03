#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-"http://localhost:8000"}
API_KEY=${API_KEY:-""}

headers=("-H" "accept: application/json")
if [[ -n "$API_KEY" ]]; then
  headers+=("-H" "x-api-key: ${API_KEY}")
fi

curl -sS "${BASE_URL}/health" "${headers[@]}" | cat
curl -sS "${BASE_URL}/agents/stats" "${headers[@]}" | cat
curl -sS "${BASE_URL}/metrics" "${headers[@]}" | head -n 20

echo "health check OK (macOS)"
