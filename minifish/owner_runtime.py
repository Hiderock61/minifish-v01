"""Codespaces owner desktop status and deliberate one-click local start.

No remote services or credentials are accessed. The operator UI can see
whether ports 8002 (private controller) and 6081 (private noVNC) *actually*
listen. It never returns process logs, URLs, passwords, or browser contents.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import stat
import subprocess
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


_PORT_TIMEOUT = 0.25
_LOCK = Lock()
_SCRIPT = Path(__file__).resolve().parent.parent / "start_g1b_mock.sh"


def _tcp_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_PORT_TIMEOUT):
            return True
    except (OSError, TimeoutError):
        return False


def _app_ready() -> bool:
    try:
        with urlopen("http://127.0.0.1:8002/g1b/status", timeout=0.8) as result:
            return result.status == 200 and "application/json" in result.headers.get("content-type", "")
    except (OSError, TimeoutError, HTTPError, URLError):
        return False


def diagnose() -> dict[str, object]:
    """Return codes, not logs or credentials. Safe to display in private UI."""
    if not os.getenv("CODESPACE_NAME"):
        return {"status": "CODESPACE_REQUIRED", "can_start": False}
    controller = _app_ready()
    screen = _tcp_ready(6081)
    if controller and screen:
        code = "READY"
    elif controller or screen:
        code = "PARTIAL_NEEDS_INSPECTION"
    elif not _SCRIPT.is_file():
        code = "SCRIPT_MISSING"
    else:
        code = "OFFLINE"
    return {"status": code, "can_start": code == "OFFLINE"}


def start_owner_desktop() -> dict[str, object]:
    """Only called after the user clicks the setup button inside PRIVATE UI."""
    with _LOCK:
        state = diagnose()
        if not state["can_start"]:
            return state
        root = Path.home() / ".local/share/minifish"
        if root.is_symlink():
            return {"status": "PRIVATE_DIRECTORY_UNSAFE", "can_start": False}
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(root.stat().st_mode) != 0o700:
            return {"status": "PRIVATE_DIRECTORY_UNSAFE", "can_start": False}
        path = root / "owner-desktop-boot.log"
        if path.is_symlink():
            return {"status": "PRIVATE_LOG_UNSAFE", "can_start": False}
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os,"O_NOFOLLOW",0), 0o600)
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
                os.close(fd)
                return {"status": "PRIVATE_LOG_UNSAFE", "can_start": False}
            with os.fdopen(fd, "ab", closefd=True) as log:
                subprocess.Popen(
                    ["bash", str(_SCRIPT)],
                    cwd=str(_SCRIPT.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError:
            return {"status": "BOOT_BLOCKED", "can_start": False}
        return {"status": "STARTING", "can_start": False}
