#!/usr/bin/env bash
# One-time Codespaces remote Chromium desktop for manual login on iPhone.
# SECURITY: Forward port 6080 PRIVATE only. Never run this for strangers.
set -euo pipefail
umask 077
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRET_DIR="$REPO_DIR/.minifish/runtime"
PASSWORD_FILE="$SECRET_DIR/vnc-password.txt"
AUTH_FILE="$SECRET_DIR/vnc-auth"
export DISPLAY="${MINIFISH_AUTH_DISPLAY:-:99}"
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
if [[ "${CODESPACES:-}" != "true" && -z "${CODESPACE_NAME:-}" && "${MINIFISH_LOCAL_TEST:-}" != "1" ]]; then
  echo "BLOCKED: remote login desktop requires GitHub Codespaces."
  exit 2
fi

# Defense in depth: GitHub's port 6080 MUST ALSO be Private.
# VNC password only protects the screen, not the port or the browser cookies.
mkdir -p "$SECRET_DIR"
chmod 700 "$REPO_DIR/.minifish" "$SECRET_DIR"
if [[ -e "$PASSWORD_FILE" || -e "$AUTH_FILE" ]]; then
  echo "BLOCKED: another or uncleanly terminated remote-login session is present."
  echo "Stop the old session and remove stale .minifish/runtime/vnc-* files after checking."
  exit 2
fi
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
printf '%s\n' "$PASSWORD" > "$PASSWORD_FILE"
chmod 600 "$PASSWORD_FILE"
x11vnc -storepasswd "$PASSWORD" "$AUTH_FILE" >/dev/null 2>&1
chmod 600 "$AUTH_FILE"
unset PASSWORD


# The VNC server binds to 127.0.0.1; the GitHub private-forwarded HTTPS
# endpoint (6080) is the ONLY remote access gate. Never set it Public.
cleanup() {
  rm -f -- "$PASSWORD_FILE" "$AUTH_FILE"
  [[ -n "${proxy_pid:-}" ]] && kill "$proxy_pid" 2>/dev/null || true
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
x11vnc -display "$DISPLAY" -localhost -rfbauth "$AUTH_FILE" -forever -rfbport "$RFB_PORT" \
  -quiet >/tmp/minifish-x11vnc.log 2>&1 &
vnc_pid=$!
sleep 1
if ! kill -0 "$vnc_pid" 2>/dev/null; then
  echo "x11vnc failed to start."; exit 1
fi
printf '\n%s\n' "MiniFish auth desktop on private port $WEB_PORT."
echo "1) Codespaces PORTS -> 6080 -> Visibility: PRIVATE (never Public)"
echo "2) iPhone Safari -> forwarded 6080 URL -> /vnc.html -> Connect"
if [[ "${MINIFISH_VNC_PASSWORD_PRINT:-1}" == "1" ]]; then
  printf "   Temporary VNC password (enter ONLY in noVNC): %s\\n" "$(cat "$PASSWORD_FILE")"
fi
echo "3) In another Codespaces terminal: DISPLAY=$DISPLAY python auth_setup.py SITE_ID"
echo "4) Log in to the visible Chromium browser; press ENTER in the terminal to verify/save"
echo "5) Press Ctrl-C HERE to shut down the one-time desktop."
echo "WARNING: PRIVATE port 6080 is mandatory; never share the VNC password."
echo "Temporary password files will be removed when this session stops."
websockify --web /usr/share/novnc "0.0.0.0:$WEB_PORT" "127.0.0.1:$RFB_PORT" &
proxy_pid=$!
wait "$proxy_pid"
