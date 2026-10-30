#!/usr/bin/env bash
set -euo pipefail

export MINIFISH_RUN_ROOT="${MINIFISH_RUN_ROOT:-$PWD/.minifish/runs}"
export MINIFISH_PROFILE_PATH="${MINIFISH_PROFILE_PATH:-$PWD/.minifish/profile.json}"

mkdir -p "$MINIFISH_RUN_ROOT" "$(dirname "$MINIFISH_PROFILE_PATH")"

if ! pgrep -f "uvicorn cloud_api:app" >/dev/null; then
  nohup bash start_iphone.sh >/tmp/minifish-api.log 2>&1 &
fi

if ! pgrep -f "python bridge_worker.py" >/dev/null; then
  nohup python bridge_worker.py >/tmp/minifish-bridge.log 2>&1 &
fi

# Browser Runtime v1: do NOT auto-start G1b here. The private owner API
# (owner_runtime.start_owner_desktop) is the only launch authority.
# The old uvicorn pgrep guard missed the VNC/noVNC startup window.

echo "MiniFish owner login: on-demand via PRIVATE 8000; PRIVATE 8002 / 6081 stay closed until ready"
echo "MiniFish API:    /tmp/minifish-api.log"
echo "MiniFish Bridge: /tmp/minifish-bridge.log"
# Run the existing Codespace updater only inside a started Codespace.
# No paid API, new Codespace, forced reset, or unattended active-login restart.
if [[ -n "${CODESPACE_NAME:-}" ]] && [[ -f tools/codespace_self_update.py ]]; then
  if ! pgrep -f '[p]ython tools/codespace_self_update.py --watch' >/dev/null; then
    mkdir -p "${HOME}/.local/share/minifish"
    nohup python tools/codespace_self_update.py --watch >"${HOME}/.local/share/minifish/self-update.log" 2>&1 &
  fi
fi
echo "Bridge ready. ChatGPT can enqueue jobs through GitHub Issues."
