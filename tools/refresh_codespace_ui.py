"""One-time, user-invoked upgrade of the already-running Codespaces control UI.

Run ONLY after a clean fast-forward update of the MiniFish PR branch.
Never deletes files, restarts the Codespace, accesses a user website,
touches credentials, or starts another remote machine. It may stop the
existing old MiniFish port-8000 service and replace it with the updated one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import time
from urllib.error import URLError, HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent
PRIVATE = Path.home() / ".local" / "share" / "minifish"
UI_HOST = "127.0.0.1"
UI_PORT = 8000


def _port_listening(port: int = UI_PORT) -> bool:
    try:
        with socket.create_connection((UI_HOST, port), timeout=0.3):
            return True
    except OSError:
        return False


def _correct_ui() -> bool:
    try:
        with urlopen(f"http://{UI_HOST}:{UI_PORT}/", timeout=0.6) as response:
            body = response.read(65536).decode("utf-8", errors="replace")
            return (
                response.status == 200
                and 'id="ownerBoot"' in body
                and 'id="ownerLoginLink"' in body
                and "/api/owner/diagnose" in body
                and "G1_PROXY_DIAG_FIX_20261018" in body
            )
    except (OSError, URLError, HTTPError, TimeoutError):
        return False


def _is_minifish_ui(argv: list[str]) -> bool:
    if not argv or not any("uvicorn" == Path(x).name for x in argv[:3]):
        # Accept 'python -m uvicorn cloud_api:app' as well as uvicorn.
        if not any(x == "uvicorn" for x in argv[:4]):
            return False
    if "cloud_api:app" not in argv:
        return False
    for i, x in enumerate(argv[:-1]):
        if x == "--port" and argv[i + 1] == "8000":
            return True
    return False


def _known_ui_processes() -> list[int]:
    ours = []
    for info in Path("/proc").iterdir():
        if not info.name.isdigit():
            continue
        try:
            if info.stat().st_uid != os.geteuid():
                continue
            argv = (info / "cmdline").read_bytes().split(b"\0")
            args = [item.decode("utf-8", errors="replace") for item in argv if item]
            if _is_minifish_ui(args):
                ours.append(int(info.name))
        except (OSError, ValueError):
            continue
    return ours


def _check_private_ports() -> bool:
    cfg = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text())
    return all(
        cfg.get("portsAttributes", {}).get(str(p), {}).get("visibility") == "private"
        for p in (8000, 8002, 6081)
    )


def _private_log() -> object:
    if PRIVATE.is_symlink():
        raise ValueError("PRIVATE_ROOT_SYMLINK")
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(PRIVATE.stat().st_mode) != 0o700:
        raise ValueError("PRIVATE_ROOT_PERMISSIONS")
    logfile = PRIVATE / "owner-control-restart.log"
    if logfile.is_symlink():
        raise ValueError("PRIVATE_LOG_SYMLINK")
    fd = os.open(
        logfile,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    meta = os.fstat(fd)
    if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600:
        os.close(fd)
        raise ValueError("PRIVATE_LOG_PERMISSIONS")
    return os.fdopen(fd, "ab")


def refresh_ui() -> str:
    if not os.getenv("CODESPACE_NAME"):
        return "BLOCKED_NOT_IN_CODESPACES"
    if not _check_private_ports():
        return "BLOCKED_PORTS_NOT_PRIVATE"
    if _correct_ui():
        return "READY_UI_ALREADY_CURRENT"

    # If port 8000 is used by an unrecognized process, leave it untouched.
    pids = _known_ui_processes()
    if len(pids) > 1 or (_port_listening() and len(pids) != 1):
        return "BLOCKED_UNKNOWN_RUNNING_SERVICE"
    if len(pids) == 1:
        pid = pids[0]
        # No kill -9, no change to bridge worker, VNC, git tree or sessions.
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            return "BLOCKED_SERVICE_PERMISSION"
        for _ in range(40):
            if not _port_listening():
                break
            time.sleep(0.2)
        if _port_listening():
            return "BLOCKED_OLD_UI_STILL_RUNNING"

    try:
        with _private_log() as log:
            subprocess.Popen(
                ["bash", "start_iphone.sh"],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except (OSError, ValueError):
        return "BLOCKED_UI_START"
    for _ in range(50):
        if _correct_ui():
            return "READY_UI_UPDATED"
        time.sleep(0.2)
    return "BLOCKED_UI_NO_RESPONSE"


def main() -> None:
    try:
        state = refresh_ui()
    except (OSError, ValueError, json.JSONDecodeError):
        state = "BLOCKED_SETUP"
    print("MINIFISH_UPDATE=" + state)
    if state.startswith("READY_"):
        print("操縦席を再読み込みしてください。ログイン準備と画面起動のボタンが表示されます。")
    else:
        print("安全のため停止しました。まだログインしないでください。")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
