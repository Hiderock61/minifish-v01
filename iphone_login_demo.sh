#!/usr/bin/env bash
# MiniFish one-command iPhone login lab: LOCAL MOCK ONLY.
# Credentials are neither requested nor used in this demo.
set -euo pipefail

cd "$(dirname "$0")"
export MINIFISH_AUTH_DISPLAY="${MINIFISH_AUTH_DISPLAY:-:99}"
export DISPLAY="$MINIFISH_AUTH_DISPLAY"
STATUS_FILE=".minifish/iphone_demo_result.txt"
mkdir -p .minifish
chmod 700 .minifish
printf 'STARTING\n' > "$STATUS_FILE"
chmod 600 "$STATUS_FILE"

mock_pid=""
desktop_pid=""
cleanup() {
  trap - EXIT INT TERM
  [[ -n "$desktop_pid" ]] && kill "$desktop_pid" 2>/dev/null || true
  [[ -n "$desktop_pid" ]] && wait "$desktop_pid" 2>/dev/null || true
  [[ -n "$mock_pid" ]] && kill "$mock_pid" 2>/dev/null || true
  [[ -n "$mock_pid" ]] && wait "$mock_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ "${CODESPACES:-}" != "true" && -z "${CODESPACE_NAME:-}" && "${MINIFISH_LOCAL_TEST:-}" != "1" ]]; then
  echo "BLOCKED: this demo expects a Codespace with PRIVATE HTTPS port 6080."
  echo "For local controlled testing only, set MINIFISH_LOCAL_TEST=1."
  printf 'NOT_IN_CODESPACES\n' > "$STATUS_FILE"
  exit 2
fi

for cmd in Xvfb x11vnc websockify; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Installing noVNC desktop dependencies..."
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xvfb x11vnc novnc websockify
    break
  fi
done

if [[ ! -f /usr/share/novnc/vnc.html ]]; then
  echo "Installing noVNC web assets..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq novnc
fi

if ! python -c 'import playwright, pytest' >/dev/null 2>&1; then
  python -m pip install -r requirements.txt -q
fi
python -m playwright install chromium >/dev/null

# Never overwrite a user's own site config or any session state.
python - <<'PY'
from pathlib import Path
import json
cfg = Path(".minifish/auth_sites.json")
example = json.loads(Path("auth_sites.example.json").read_text(encoding="utf-8"))["sites"][0]
if cfg.exists():
    data = json.loads(cfg.read_text(encoding="utf-8"))
    sites = data.get("sites", [])
    if any(s.get("site_id") == "mock_site" for s in sites):
        if not any(s.get("site_id") == "mock_site" and s.get("base_url") == example["base_url"] for s in sites):
            raise SystemExit("mock_site already exists with a different origin; refusing to overwrite")
    else:
        sites.append(example)
        data["sites"] = sites
        cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
else:
    cfg.write_text(json.dumps({"sites": [example]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
cfg.chmod(0o600)
PY

echo "Starting LOCAL fake account server (not a real points site)"
python -u mock_auth_site.py >/tmp/minifish-mock-auth.log 2>&1 &
mock_pid=$!
for i in {1..30}; do
  if curl --silent --fail http://127.0.0.1:8765/login >/dev/null; then break; fi
  if ! kill -0 "$mock_pid" 2>/dev/null; then
    echo "Mock auth server failed (port 8765 may be in use)."; exit 2
  fi
  sleep 1
done

echo "Starting PRIVATE remote Chromium desktop"
bash start_auth_desktop.sh >/tmp/minifish-auth-desktop.log 2>&1 &
desktop_pid=$!
for i in {1..30}; do
  if curl --silent --fail http://127.0.0.1:6080/vnc.html >/dev/null; then break; fi
  if ! kill -0 "$desktop_pid" 2>/dev/null; then
    echo "Desktop startup failed. See /tmp/minifish-auth-desktop.log"; exit 2
  fi
  sleep 1
done
if ! curl --silent --fail http://127.0.0.1:6080/vnc.html >/dev/null; then
  echo "Desktop did not respond on local port 6080"; exit 2
fi

echo ""
echo "==============================================="
echo "  🐟 MiniFish iPhone login demo READY"
echo "==============================================="
echo "In Codespaces PORTS: choose 6080 -> Port Visibility PRIVATE."
echo "Open the forwarded HTTPS URL with /vnc.html in iPhone Safari."
echo "Tap Connect, then tap Sign in (no password) in Chromium."
echo "No real login or passwords in this experiment."
echo "This command automatically checks save -> browser restart -> restore."
echo ""

# Headed browser must run in the very same X display that noVNC exposes.
printf 'AWAITING_MOCK_LOGIN\n' > "$STATUS_FILE"
if DISPLAY="$MINIFISH_AUTH_DISPLAY" python -u auth_setup.py mock_site --auto --timeout 600; then
  printf 'RESTORE_CHECK\n' > "$STATUS_FILE"
  if python -u auth_check.py mock_site; then
    printf 'PASS: IPHONE_MOCK_LOGIN_RESTORE\n' > "$STATUS_FILE"
    echo ""
    echo "✅ PASS: human mock login saved and restored in a fresh Chromium."
    echo "Close the noVNC Safari tab. This temporary desktop is shutting down."
  else
    printf 'FAIL: RESTORE_CHECK\n' > "$STATUS_FILE"
    echo "❌ FAIL: manual mock login saved but headless restore failed."
    exit 1
  fi
else
  printf 'FAIL: MOCK_LOGIN_OR_TIMEOUT\n' > "$STATUS_FILE"
  echo "❌ FAIL: login proof not found or user interaction timed out."
  exit 1
fi
