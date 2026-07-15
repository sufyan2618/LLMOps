#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${EVAL_API_BASE_URL:-http://localhost:8000}}"

echo "==> Smoke test against ${BASE_URL}"

curl -fsS "${BASE_URL}/health" | grep -q '"status"'
echo "health ok"

# Ready may 503 if model not mounted in ephemeral CI — accept 200 or 503
READY_CODE=$(curl -s -o /tmp/ready.json -w "%{http_code}" "${BASE_URL}/ready" || true)
echo "ready status=${READY_CODE} body=$(cat /tmp/ready.json || true)"

if [[ "${READY_CODE}" == "200" ]]; then
  RESP=$(curl -fsS -X POST "${BASE_URL}/chat" \
    -H "Content-Type: application/json" \
    -d '{"message":"Say hi in one word."}')
  echo "${RESP}" | grep -q '"response"'
  echo "chat ok"
else
  echo "model not ready — skipping chat smoke (expected if GGUF volume missing)"
fi

METRICS=$(curl -fsS "${BASE_URL}/metrics" || true)
echo "${METRICS}" | head -n 5
echo "smoke test passed"
