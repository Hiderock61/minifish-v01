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
                and "G1_OWNER_START_NONCE_20261021" in body
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


def _private_log(name: str = "owner-control-restart.log") -> object:
    if PRIVATE.is_symlink():
        raise ValueError("PRIVATE_ROOT_SYMLINK")
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(PRIVATE.stat().st_mode) != 0o700:
        raise ValueError("PRIVATE_ROOT_PERMISSIONS")
    if name not in ("owner-control-restart.log", "owner-login-restart.log"):
        raise ValueError("PRIVATE_LOG_NAME_UNSAFE")
    logfile = PRIVATE / name
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



def _is_minifish_login(argv: list[str]) -> bool:
    if not argv:
        return False
    is_uvicorn = (any(Path(x).name == "uvicorn" for x in argv[:3])
                  or "uvicorn" in argv[:4])
    if not is_uvicorn or "g1b_mock_app:app" not in argv:
        return False
    return any(x == "--port" and argv[i + 1] == "8002"
               for i, x in enumerate(argv[:-1]))


def _known_login_processes() -> list[int]:
    ours = []
    for info in Path("/proc").iterdir():
        if not info.name.isdigit():
            continue
        try:
            if info.stat().st_uid != os.geteuid():
                continue
            argv = (info / "cmdline").read_bytes().split(b"\0")
            args = [item.decode("utf-8", errors="replace") for item in argv if item]
            if _is_minifish_login(args):
                ours.append(int(info.name))
        except (OSError, ValueError):
            continue
    return ours


def _login_controller_current() -> bool:
    try:
        with urlopen("http://127.0.0.1:8002/login-ready", timeout=0.8) as response:
            content = response.read(32768).decode("utf-8", errors="replace")
            return (
                response.status == 200
                and "G1_OWNER_8002_LIVE_PROBE_20261021" in content
                and "クラウドワークス" in content
            )
    except (OSError, HTTPError, URLError, TimeoutError):
        return False


def _owner_login_idle() -> bool:
    try:
        with urlopen("http://127.0.0.1:8002/g1/owner/status", timeout=0.8) as response:
            if response.status != 200:
                return False
            status = json.loads(response.read(8192))
            return status.get("busy") is False
    except (OSError, HTTPError, URLError, TimeoutError, ValueError):
        return False


def refresh_login_controller() -> str:
    """Restart only our known PRIVATE login controller, never an active login.

    The existing start_g1b_mock.sh supervises both the 8002 controller and
    VNC/noVNC. Stopping its exact uvicorn child allows its cleanup trap to
    close the old desktop before one guarded fresh start. No rebuild, token,
    new Codespace or site access happens here.
    """
    if not os.getenv("CODESPACE_NAME"):
        return "BLOCKED_NOT_IN_CODESPACES"
    if not _check_private_ports():
        return "BLOCKED_PORTS_NOT_PRIVATE"
    if _login_controller_current():
        return "READY_LOGIN_ALREADY_CURRENT"
    pids = _known_login_processes()
    if len(pids) > 1 or (_port_listening(8002) and len(pids) != 1):
        return "BLOCKED_UNKNOWN_LOGIN_SERVICE"
    if len(pids) == 1:
        if not _owner_login_idle():
            return "BLOCKED_LOGIN_ACTIVE_OR_UNREADABLE"
        try:
            os.kill(pids[0], signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return "BLOCKED_LOGIN_STOP"
        # Wait until the supervising shell closes its VNC/noVNC listeners.
        for _ in range(80):
            if not any(_port_listening(p) for p in (8002, 6081, 5911)):
                break
            time.sleep(0.25)
        if any(_port_listening(p) for p in (8002, 6081, 5911)):
            return "BLOCKED_OLD_LOGIN_STILL_RUNNING"
    elif any(_port_listening(p) for p in (6081, 5911)):
        return "BLOCKED_PARTIAL_LOGIN_DESKTOP"

    if not (ROOT / "start_g1b_mock.sh").is_file():
        return "BLOCKED_LOGIN_SCRIPT_MISSING"
    try:
        with _private_log("owner-login-restart.log") as log:
            subprocess.Popen(
                ["bash", "start_g1b_mock.sh"],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except (OSError, ValueError):
        return "BLOCKED_LOGIN_START"
    for _ in range(120):
        if _login_controller_current() and _port_listening(6081):
            return "READY_LOGIN_UPDATED"
        time.sleep(0.25)
    return "BLOCKED_LOGIN_NO_RESPONSE"


def main() -> None:
    try:
        state = refresh_ui()
    except (OSError, ValueError, json.JSONDecodeError):
        state = "BLOCKED_SETUP"
    print("MINIFISH_UPDATE=" + state)
    if not state.startswith("READY_"):
        print("操縦席の更新で安全停止しました。まだログインしないでください。")
        raise SystemExit(1)
    try:
        login_state = refresh_login_controller()
    except (OSError, ValueError, json.JSONDecodeError):
        login_state = "BLOCKED_LOGIN_SETUP"
    print("MINIFISH_LOGIN_UPDATE=" + login_state)
    if login_state.startswith("READY_LOGIN_"):
        print("MiniFishの操縦席を再読み込みし、青いログインボタンを開いてください。")
    else:
        print("ログイン装置は安全停止しました。まだログインしないでください。")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
