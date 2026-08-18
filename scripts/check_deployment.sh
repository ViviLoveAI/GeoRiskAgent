#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
HEALTH_URL="${BASE_URL%/}/health"

echo "Checking FastAPI backend at ${HEALTH_URL}"

if curl -fsS "${HEALTH_URL}" >/dev/null; then
  echo "FastAPI backend reachable"
else
  echo "FastAPI backend not reachable"
  exit 1
fi
