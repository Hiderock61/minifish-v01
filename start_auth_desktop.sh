#!/usr/bin/env bash
# One-time Codespaces remote Chromium desktop for manual login on iPhone.
# SECURITY: Forward port 6080 PRIVATE only. Never run this for strangers.
set -euo pipefail
export DISPLAY="${DISPLAY:-:99}"
RFB_PORT=5901
WEB_PORT=6080

for cmd in Xvfb x11vnc websockify; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing $cmd. Install once in the Codespace:"
    echo "  sudo apt-get update && sudo apt-get install -y xvfb x11vnc novnc websockify"
    exit 2
  fi
done
if [[ ! -f /usr/share/novnc/vnc.html ]]; then
  echo "NoVNC files missing. Install the 'novnc' package."; exit 2
fi
if [[ -z "${CODESPACES:-}" ]]; then
  echo "WARNING: intended for GitHub Codespaces private port forwarding only."
  echo "Press Ctrl-C to stop if this environment is not trusted."
fi

# The VNC server binds to 127.0.0.1; the GitHub private-forwarded HTTPS
# endpoint (6080) is the ONLY remote access gate. Never set it Public.
cleanup() {
  [[ -n "${vnc_pid:-}" ]] && kill "$vnc_pid" 2>/dev/null || true
  [[ -n "${xvfb_pid:-}" ]] && kill "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp >/tmp/minifish-xvfb.log 2>&1 &
xvfb_pid=$!
sleep 1
if ! kill -0 "$xvfb_pid" 2>/dev/null; then
  echo "Xvfb failed to start. Check existing DISPLAY and /tmp/minifish-xvfb.log"; exit 1
fi
x11vnc -display "$DISPLAY" -localhost -nopw -forever -shared -rfbport "$RFB_PORT" \
  -quiet >/tmp/minifish-x11vnc.log 2>&1 &
vnc_pid=$!
sleep 1
if ! kill -0 "$vnc_pid" 2>/dev/null; then
  echo "x11vnc failed to start."; exit 1
fi
printf '\n%s\n' "MiniFish auth desktop on private port $WEB_PORT."
echo "1) Codespaces PORTS -> 6080 -> Visibility: PRIVATE (never Public)"
echo "2) iPhone Safari -> forwarded 6080 URL -> /vnc.html -> Connect"
echo "3) In another Codespaces terminal: DISPLAY=$DISPLAY python auth_setup.py SITE_ID"
echo "4) Log in to the visible Chromium browser; press ENTER in the terminal to verify/save"
echo "5) Press Ctrl-C HERE to shut down the one-time desktop."
echo "WARNING: This is a proof-of-concept login path, not a hardened password manager."
exec websockify --web /usr/share/novnc "0.0.0.0:$WEB_PORT" "127.0.0.1:$RFB_PORT"
