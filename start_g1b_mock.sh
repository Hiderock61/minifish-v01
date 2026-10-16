#!/usr/bin/env bash
set -euo pipefail

# G1b MOCK ONLY: no external sites, real credentials or persistent VNC port 6080.
# desktop-lite supplies tigervncserver/noVNC but its default desktop is NOT used.
if [[ -z "${CODESPACE_NAME:-}" && "${MINIFISH_G1B_LOCAL_TEST:-}" != "1" ]]; then
  echo "G1B_BLOCKED_NOT_PRIVATE_CODESPACE"
  exit 1
fi

umask 077
private_dir="$HOME/.local/share/minifish/g1b-mock-only"
mkdir -p "$private_dir"
chmod 700 "$private_dir"

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
if [[ -e "$private_dir/vnc-passwd" || -L "$private_dir/vnc-passwd" ]]; then
  echo "G1B_BLOCKED_VNC_ALREADY_CONFIGURED"
  exit 1
fi
printf '%s\n' "$(cat "$private_dir/vnc-password.txt")" | vncpasswd -f > "$private_dir/vnc-passwd"
chmod 600 "$private_dir/vnc-passwd"

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
tigervncserver :11 -geometry 1280x768 -depth 24 -rfbport 5911 \
  -localhost -SecurityTypes VncAuth -passwd "$private_dir/vnc-passwd" \
  -desktop MiniFish-G1b >/dev/null

# Do not expose 8002 until the private mock desktop successfully started.
nohup "${proxies[0]}" --listen 6081 --vnc localhost:5911 \
  >"$private_dir/novnc.log" 2>&1 &
export DISPLAY=:11

echo "G1B_PRIVATE_MOCK_READY=1 PORTS=8002,6081"
exec uvicorn g1b_mock_app:app --host 0.0.0.0 --port 8002 \
  --no-access-log --log-level warning
