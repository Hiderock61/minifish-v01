#!/usr/bin/env bash
# CI smoke: HTTP noVNC loads and browser WebSocket carries an RFB handshake.
# This does not constitute a physical iPhone Safari test.
set -euo pipefail
cd "$(dirname "$0")/.."
log="$(mktemp)"
export MINIFISH_AUTH_DISPLAY=:98
desktop_pid=""
cleanup() {
  [[ -n "$desktop_pid" ]] && kill "$desktop_pid" 2>/dev/null || true
  [[ -n "$desktop_pid" ]] && wait "$desktop_pid" 2>/dev/null || true
  rm -f "$log"
}
trap cleanup EXIT
bash start_auth_desktop.sh >"$log" 2>&1 &
desktop_pid=$!
ready=0
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:6080/vnc.html >/dev/null 2>&1; then
    ready=1
    break
  fi
  kill -0 "$desktop_pid" 2>/dev/null || break
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "FAIL: noVNC HTTP endpoint unavailable"
  cat "$log"
  exit 1
fi
python - <<'PY'
from websockets.sync.client import connect
with connect("ws://127.0.0.1:6080/websockify", subprotocols=["binary"], open_timeout=5) as conn:
    banner = conn.recv(timeout=5)
    if isinstance(banner, str):
        banner = banner.encode()
    assert banner.startswith(b"RFB "), repr(banner)
print("PASS: noVNC HTTP and browser-to-RFB WebSocket handshake")
PY
