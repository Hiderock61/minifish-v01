#!/usr/bin/env bash
set -euo pipefail

export MINIFISH_RUN_ROOT="${MINIFISH_RUN_ROOT:-$PWD/.minifish/runs}"
export MINIFISH_PROFILE_PATH="${MINIFISH_PROFILE_PATH:-$PWD/.minifish/profile.json}"

mkdir -p "$MINIFISH_RUN_ROOT" "$(dirname "$MINIFISH_PROFILE_PATH")"

# Codespaces: guarded one-shot launch + fixed-code result receipt. This checks
# the actual owner HTTP response, not merely whether nohup was invoked.
# No Runtime/VNC start here; that remains exclusively owner-authorized.
api_start_status=0
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  if [[ -f tools/api_bootstrap.py ]]; then
    python tools/api_bootstrap.py --ensure || api_start_status=$?
  else
    echo "MINIFISH_API_BOOT=FAIL_BOOTSTRAP_MISSING"
    api_start_status=2
  fi
else
  # Preserve non-Codespaces local development behavior.
  if ! pgrep -f '[u]vicorn cloud_api:app' >/dev/null; then
    nohup bash start_iphone.sh >/tmp/minifish-api.log 2>&1 &
  fi
fi

if ! pgrep -f '[p]ython bridge_worker.py' >/dev/null; then
  nohup python bridge_worker.py >/tmp/minifish-bridge.log 2>&1 &
fi

# Browser Runtime v1: do NOT auto-start G1b here. The private owner API
# (owner_runtime.start_owner_desktop) is the only launch authority.
# The old uvicorn pgrep guard missed the VNC/noVNC startup window.

echo "MiniFish owner login: on-demand via PRIVATE 8000; PRIVATE 8002 / 6081 stay closed until ready"
echo "MiniFish API:    ~/.local/share/minifish/api-bootstrap/uvicorn.log (private, Codespaces)"
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
if (( api_start_status != 0 )); then
  echo "MINIFISH_API_BOOT=POSTSTART_FAILED"
  exit "$api_start_status"
fi
