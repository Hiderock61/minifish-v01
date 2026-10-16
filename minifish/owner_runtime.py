"""Private Codespaces login desktop: self-check, guarded start, safe diagnosis.

Reads actual 8002/6081 listeners and a fixed set of known startup failure
codes. Never returns or logs credentials, raw exceptions, remote page
content, cookies, or arbitrary log data. Never starts a billable service.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import time
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_PORT_TIMEOUT = 0.25
_BOOT_GRACE_SECONDS = 35
_LOCK = Lock()
_SCRIPT = Path(__file__).resolve().parent.parent / "start_g1b_mock.sh"
_BOOT_REQUESTED_AT = 0.0
# Bounded, pre-approved labels only. Never pass raw exception lines to UI.
_START_ERRORS = (
    ("G1B_BLOCKED_NOT_PRIVATE_CODESPACE", "CODESPACE_REQUIRED"),
    ("G1B_BLOCKED_DESKTOP_MISSING", "DESKTOP_MISSING"),
    ("G1B_BLOCKED_NOVNC_PROXY_MISSING", "NOVNC_MISSING"),
    ("G1B_BLOCKED_DISPLAY_ALREADY_IN_USE", "DESKTOP_IN_USE"),
    ("G1B_BLOCKED_VNC_SYMLINK", "AUTH_FILE_UNSAFE"),
    ("G1B_PASSWORD_SYMLINK_BLOCKED", "AUTH_FILE_UNSAFE"),
    ("G1B_PASSWORD_PERMISSIONS_UNSAFE", "AUTH_FILE_UNSAFE"),
    ("G1B_PASSWORD_INVALID", "AUTH_FILE_UNSAFE"),
)


def _tcp_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_PORT_TIMEOUT):
            return True
    except (OSError, TimeoutError):
        return False


def _app_ready() -> bool:
    """Require the NEW private login endpoint, not an obsolete 8002 app."""
    name = os.getenv("CODESPACE_NAME", "")
    if not name:
        return False
    try:
        request = Request(
            "http://127.0.0.1:8002/login-ready",
            headers={"Host": f"{name}-8002.app.github.dev"},
        )
        with urlopen(request, timeout=0.85) as result:
            return (
                result.status == 200
                and "text/html" in result.headers.get("content-type", "")
                and "クラウドワークス" in result.read(24_000).decode("utf-8", errors="replace")
            )
    except (OSError, TimeoutError, HTTPError, URLError):
        return False


def _private_log_path() -> Path:
    return Path.home() / ".local/share/minifish/owner-desktop-boot.log"


def _known_failure() -> str:
    """Inspect only last 4 KB, mapping known codes to safe fixed labels."""
    log = _private_log_path()
    try:
        if log.is_symlink():
            return "PRIVATE_LOG_UNSAFE"
        metadata = log.stat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            return "PRIVATE_LOG_UNSAFE"
        with log.open("rb") as stream:
            stream.seek(max(0, metadata.st_size - 4096))
            body = stream.read(4096).decode("utf-8", errors="replace")
        # Take the latest known code; no user-influenced text is returned.
        events = [(body.rfind(raw), fixed) for raw, fixed in _START_ERRORS]
        events = [e for e in events if e[0] >= 0]
        return max(events)[1] if events else "BOOT_BLOCKED"
    except (OSError, ValueError):
        return "BOOT_BLOCKED"


def _desktop_dependencies_present() -> bool:
    # Require installed tooling, never try apt install from the control UI.
    return bool(shutil.which("vncpasswd") and shutil.which("tigervncserver")
                and list(Path("/usr/local/novnc").glob("noVNC*/utils/novnc_proxy")))


def diagnose() -> dict[str, object]:
    """Fixed status and one-click eligibility for an owner-private control UI."""
    global _BOOT_REQUESTED_AT
    if not os.getenv("CODESPACE_NAME"):
        return {"status": "CODESPACE_REQUIRED", "can_start": False}
    screen = _tcp_ready(6081)
    controller = _app_ready()
    if controller and screen:
        _BOOT_REQUESTED_AT = 0
        return {"status": "READY", "can_start": False}
    if controller or screen:
        return {"status": "PARTIAL_NEEDS_INSPECTION", "can_start": False}
    if not _SCRIPT.is_file():
        return {"status": "SCRIPT_MISSING", "can_start": False}
    if _BOOT_REQUESTED_AT:
        if time.monotonic() - _BOOT_REQUESTED_AT < _BOOT_GRACE_SECONDS:
            return {"status": "STARTING", "can_start": False}
        return {"status": _known_failure(), "can_start": True}
    # No launch has been requested via this process; a failed old startup
    # can be retried manually with one click.
    return {"status": "OFFLINE", "can_start": True}


def start_owner_desktop() -> dict[str, object]:
    """One guarded attempt; never touches the user's Codespaces lifecycle."""
    global _BOOT_REQUESTED_AT
    with _LOCK:
        state = diagnose()
        if not state["can_start"]:
            return state
        if not _desktop_dependencies_present():
            return {"status": "DESKTOP_MISSING", "can_start": False}
        root = Path.home() / ".local/share/minifish"
        if root.is_symlink():
            return {"status": "PRIVATE_DIRECTORY_UNSAFE", "can_start": False}
        # Only protect this newly created directory; never delete or
        # recursively change existing workspace data.
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(root.stat().st_mode) != 0o700:
            return {"status": "PRIVATE_DIRECTORY_UNSAFE", "can_start": False}
        path = _private_log_path()
        if path.is_symlink():
            return {"status": "PRIVATE_LOG_UNSAFE", "can_start": False}
        try:
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_APPEND
                | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
            if (not stat.S_ISREG(os.fstat(fd).st_mode)
                    or stat.S_IMODE(os.fstat(fd).st_mode) != 0o600):
                os.close(fd)
                return {"status": "PRIVATE_LOG_UNSAFE", "can_start": False}
            with os.fdopen(fd, "ab", closefd=True) as log:
                subprocess.Popen(
                    ["bash", str(_SCRIPT)],
                    cwd=str(_SCRIPT.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            # A rapid double-click will not spawn a second desktop.
            _BOOT_REQUESTED_AT = time.monotonic()
        except OSError:
            return {"status": "BOOT_BLOCKED", "can_start": False}
        return {"status": "STARTING", "can_start": False}
