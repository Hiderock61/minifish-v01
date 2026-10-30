#!/usr/bin/env bash
set -euo pipefail

# G1b MOCK ONLY: no external sites, real credentials or persistent VNC port 6080.
# desktop-lite supplies tigervncserver/noVNC but its default desktop is NOT used.
if [[ -z "${CODESPACE_NAME:-}" && "${MINIFISH_G1B_LOCAL_TEST:-}" != "1" ]]; then
  echo "G1B_BLOCKED_NOT_PRIVATE_CODESPACE"
  exit 1
fi

umask 077
# Fixed diagnostic stage codes only. Raw VNC errors remain in the PRIVATE boot log.
startup_stage="INITIAL"
report_boot_error() {
  case "$startup_stage" in
    INITIAL|PASSWORD|VNC|NOVNC|CONTROLLER) echo "G1B_START_FAILED_${startup_stage}" ;;
    *) echo "G1B_START_FAILED_UNKNOWN" ;;
  esac
}
trap 'report_boot_error' ERR
private_dir="$HOME/.local/share/minifish/g1b-mock-only"
if [[ -L "$private_dir" ]]; then
  echo "G1B_BLOCKED_PRIVATE_DIR_UNSAFE"
  exit 1
fi
mkdir -p "$private_dir"
chmod 700 "$private_dir"

# Lock the entire VNC -> noVNC -> controller lifetime, not merely the
# uvicorn phase. A second invocation fails closed without killing the first.
runtime_lock="$private_dir/runtime.lock"
if [[ -L "$runtime_lock" ]]; then
  echo "G1B_BLOCKED_RUNTIME_LOCK_UNSAFE"
  exit 1
fi
command -v flock >/dev/null || { echo "G1B_BLOCKED_RUNTIME_LOCK_MISSING"; exit 1; }
umask 077
exec 9>"$runtime_lock"
if ! flock -n 9; then
  echo "G1B_BLOCKED_ALREADY_STARTING"
  exit 1
fi

# Only fixed state labels and PID in a private, atomic status record.
# The owner API verifies that the writer PID is still a live launcher.
write_stage() {
  local temp
  temp="$(mktemp "$private_dir/.runtime-stage-XXXXXXXX")"
  chmod 600 "$temp"
  printf '%s %s\n' "$" "$1" >"$temp"
  mv -f "$temp" "$private_dir/runtime.stage"
}
write_stage STARTING_VNC

startup_stage="PASSWORD"
# Fail closed on symlink/unsafe file. Random password lives ONLY in Codespaces home.
python - "$private_dir/vnc-password.txt" <<'PY'
import os
from pathlib import Path
import secrets
import stat
import sys

p = Path(sys.argv[1])
if p.is_symlink():
    raise SystemExit("G1B_PASSWORD_SYMLINK_BLOCKED")
if p.exists():
    meta = p.stat()
    if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600:
        raise SystemExit("G1B_PASSWORD_PERMISSIONS_UNSAFE")
    value = p.read_text(encoding="ascii")
    if len(value) != 8 or not value.isalnum():
        raise SystemExit("G1B_PASSWORD_INVALID")
else:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    value = "".join(secrets.choice(alphabet) for _ in range(8))
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(value)
PY

if ! command -v vncpasswd >/dev/null || ! command -v tigervncserver >/dev/null; then
  echo "G1B_BLOCKED_DESKTOP_MISSING"
  exit 1
fi

# VncAuth uses up to 8 characters; all 8 are generated with OS randomness.
# The auth file is private; the plaintext password is NOT sent to stdout/logs.
if [[ -L "$private_dir/vnc-passwd" ]]; then
  echo "G1B_BLOCKED_VNC_SYMLINK"
  exit 1
fi
auth_temp="$(mktemp "$private_dir/.vnc-auth-XXXXXXXX")"
chmod 600 "$auth_temp"
printf '%s\n' "$(cat "$private_dir/vnc-password.txt")" | vncpasswd -f > "$auth_temp"
mv -f "$auth_temp" "$private_dir/vnc-passwd"

shopt -s nullglob
proxies=(/usr/local/novnc/noVNC*/utils/novnc_proxy)
if (( ${#proxies[@]} != 1 )); then
  echo "G1B_BLOCKED_NOVNC_PROXY_MISSING"
  exit 1
fi

# Dedicated display :11, not desktop-lite's built-in (publicly known) :1.
# RFB is local-only; only private GitHub port forwarding exposes web 6081.
if [[ -e /tmp/.X11-unix/X11 ]]; then
  echo "G1B_BLOCKED_DISPLAY_ALREADY_IN_USE"
  exit 1
fi
startup_stage="VNC"
if ! command -v fluxbox >/dev/null; then
  echo "G1B_BLOCKED_WINDOW_MANAGER_MISSING"
  exit 1
fi
# Explicitly launch Fluxbox so a fresh desktop can stay alive on :11.
# Default sessions may exit immediately on minimal Codespaces images.
tigervncserver :11 -geometry 1280x768 -depth 24 -rfbport 5911 \
  -localhost -SecurityTypes VncAuth -passwd "$private_dir/vnc-passwd" \
  -xstartup "$(command -v fluxbox)" -desktop MiniFish-G1b >/dev/null

# Do not expose 8002 until the private mock desktop successfully started.
startup_stage="NOVNC"
write_stage STARTING_NOVNC
nohup "${proxies[0]}" --listen 6081 --vnc localhost:5911 \
  >"$private_dir/novnc.log" 2>&1 &
proxy_pid=$!
export DISPLAY=:11

cleanup() {
  kill "$proxy_pid" >/dev/null 2>&1 || true
  tigervncserver -kill :11 >/dev/null 2>&1 || true
  rm -f "$private_dir/vnc-password.txt" "$private_dir/vnc-passwd"
}
trap cleanup EXIT
trap 'exit 0' TERM INT

# The forwardPorts list is not evidence that a server listens. Verify both
# local services before marking the controller ready.
python - <<'PY'
import socket, time, sys
for port in (5911, 6081):
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.2)
    else:
        print("G1B_START_FAILED_LOCAL_LISTENER", flush=True)
        sys.exit(1)
PY
startup_stage="CONTROLLER"
write_stage STARTING_CONTROLLER
trap - ERR
echo "G1B_PRIVATE_MOCK_READY=1 PORTS=8002,6081"
uvicorn g1b_mock_app:app --host 0.0.0.0 --port 8002 \
  --no-access-log --log-level warning
