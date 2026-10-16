#!/usr/bin/env bash
set -euo pipefail

# G1b is MOCK ONLY: never hand real passwords to this gateway.
# Codespaces desktop-lite supplies the private display and noVNC.
if [[ -z "${DISPLAY:-}" ]]; then
  echo "G1B_BLOCKED_NO_PRIVATE_DESKTOP"
  exit 1
fi
exec uvicorn g1b_mock_app:app --host 0.0.0.0 --port 8002 --no-access-log --log-level warning
