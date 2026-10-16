#!/usr/bin/env bash
set -euo pipefail

export MINIFISH_RUN_ROOT="${MINIFISH_RUN_ROOT:-$PWD/.minifish/runs}"
export MINIFISH_PROFILE_PATH="${MINIFISH_PROFILE_PATH:-$PWD/.minifish/profile.json}"

mkdir -p "$MINIFISH_RUN_ROOT" "$(dirname "$MINIFISH_PROFILE_PATH")"

# Codespaces only: provision the private receiver once and announce ONLY the
# public half on the existing Issue #5. Never print keys or article content.
if [[ "${CODESPACES:-false}" == "true" ]]; then
  if ! python -m minifish.chat_handoff bootstrap; then
    echo "MiniFish handoff BLOCKED: check private receiver setup (no key material logged)"
  fi
fi

if ! pgrep -f "uvicorn cloud_api:app" >/dev/null; then
  nohup bash start_iphone.sh >/tmp/minifish-api.log 2>&1 &
fi

if ! pgrep -f "python bridge_worker.py" >/dev/null; then
  nohup python bridge_worker.py >/tmp/minifish-bridge.log 2>&1 &
fi

echo "MiniFish API:    /tmp/minifish-api.log"
echo "MiniFish Bridge: /tmp/minifish-bridge.log"
echo "Bridge ready. ChatGPT can enqueue jobs through GitHub Issues."
