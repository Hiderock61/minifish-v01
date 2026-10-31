#!/usr/bin/env python3
"""One-shot, fail-closed Codespaces API bootstrap with a privacy-safe receipt.

Runs only when explicitly called with --ensure. Never creates a Codespace,
restarts an occupied port, starts a browser, transmits secrets, or retries
forever. Intended for devcontainer postStartCommand, not for owner Runtime.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
PROC_ROOT = Path("/proc")
STORAGE = Path.home() / ".local/share/minifish/api-bootstrap"
RECEIPT = STORAGE / "status.json"
LOG = STORAGE / "uvicorn.log"
LOCK = STORAGE / "bootstrap.lock"
KNOWN_CODES = frozenset({
    "READY_ALREADY", "READY_SPAWNED", "HOLD_NOT_CODESPACE", "HOLD_SOURCE_MISMATCH",
    "HOLD_PRIVATE_PORTS", "HOLD_PRIVATE_DIRECTORY", "HOLD_LOCK_BUSY",
    "HOLD_PORT_OCCUPIED", "HOLD_PROCESS_PRESENT", "HOLD_TIMEOUT_ALIVE",
    "FAIL_SCRIPT_MISSING", "FAIL_SPAWN", "FAIL_CHILD_EXITED", "FAIL_TIMEOUT_EXITED",
    "HOLD_WRONG_MODE", "HOLD_SOURCE_READ_ERROR",
})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def write_event(code: str, *, exit_code: int | None = None) -> None:
    """Store fixed status only; never raw stack traces, env vars, or responses."""
    if code not in KNOWN_CODES:
        raise ValueError("unknown receipt code")
    body = {
        "schema": 1, "state": code,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exit_code": exit_code if type(exit_code) is int and 0 <= exit_code <= 255 else None,
    }
    # Do not change existing files or follow symlinks.
    if RECEIPT.is_symlink():
        raise OSError("unsafe receipt")
    name = STORAGE / (".status.tmp.%d" % os.getpid())
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, RECEIPT)
    finally:
        name.unlink(missing_ok=True)
    print("MINIFISH_API_BOOT=" + code, flush=True)


def secure_storage() -> bool:
    for directory in (STORAGE.parent.parent, STORAGE.parent):
        if directory.is_symlink():
            return False
    if STORAGE.is_symlink():
        return False
    try:
        STORAGE.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = STORAGE.stat()
        return stat.S_ISDIR(mode.st_mode) and mode.st_uid == os.geteuid() and stat.S_IMODE(mode.st_mode) == 0o700
    except OSError:
        return False


def source_guard() -> str | None:
    if not re.fullmatch(r"[a-z0-9-]+", os.environ.get("CODESPACE_NAME", "")):
        return "HOLD_NOT_CODESPACE"
    if not all((ROOT / file).is_file() for file in ("cloud_api.py", "start_iphone.sh", "start_all.sh")):
        return "HOLD_SOURCE_MISMATCH"
    try:
        data = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text(encoding="utf-8"))
        if data.get("postStartCommand") != "bash start_all.sh":
            return "HOLD_SOURCE_MISMATCH"
        if any(data.get("portsAttributes", {}).get(str(p), {}).get("visibility") != "private"
               for p in (8000, 8002, 6081)):
            return "HOLD_PRIVATE_PORTS"
    except (OSError, ValueError, TypeError):
        return "HOLD_SOURCE_READ_ERROR"
    return None


def port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.3):
            return True
    except OSError:
        return False


def owner_http_ok() -> bool:
    """Read-only local GET, never follow redirect. Check real owner UI identity."""
    try:
        req = Request("http://127.0.0.1:8000/", headers={"Cache-Control": "no-store"})
        with OPENER.open(req, timeout=1) as resp:
            if resp.status != 200:
                return False
            content = resp.read(160000).decode("utf-8", "replace")
        return ('id="ownerBoot"' in content and '/api/owner/diagnose' in content)
    except (HTTPError, URLError, OSError, TimeoutError):
        return False


def existing_owner_process() -> bool:
    """Exact process-argv tokens, unlike pgrep -f substring/self matches."""
    for directory in PROC_ROOT.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            raw = (directory / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        args = [x.decode("utf-8", "replace") for x in raw if x]
        if "cloud_api:app" not in args:
            continue
        if not any(Path(s).name == "uvicorn" or s == "uvicorn" for s in args):
            # python -m uvicorn
            if not any(args[i:i+2] == ["-m", "uvicorn"] for i in range(len(args)-1)):
                continue
        if any(args[i:i+2] == ["--port", "8000"] for i in range(len(args)-1)):
            return True
    return False


def start_once(window_seconds: float = 16.0, poll_seconds: float = 0.5) -> str:
    guard = source_guard()
    if guard:
        return guard
    if not secure_storage():
        return "HOLD_PRIVATE_DIRECTORY"
    try:
        lock_fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError:
        return "HOLD_PRIVATE_DIRECTORY"
    try:
        mode = os.fstat(lock_fd)
        if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or stat.S_IMODE(mode.st_mode) != 0o600:
            return "HOLD_PRIVATE_DIRECTORY"
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "HOLD_LOCK_BUSY"
        try:
            child_exit_code = None
            if owner_http_ok():
                outcome = "READY_ALREADY"
            elif port_open():
                outcome = "HOLD_PORT_OCCUPIED"
            elif existing_owner_process():
                outcome = "HOLD_PROCESS_PRESENT"
            elif not (ROOT / "start_iphone.sh").is_file():
                outcome = "FAIL_SCRIPT_MISSING"
            else:
                try:
                    if LOG.is_symlink():
                        outcome = "HOLD_PRIVATE_DIRECTORY"
                    else:
                        fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
                        info = os.fstat(fd)
                        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                                or stat.S_IMODE(info.st_mode) != 0o600):
                            os.close(fd)
                            outcome = "HOLD_PRIVATE_DIRECTORY"
                        else:
                            with os.fdopen(fd, "ab") as stream:
                                child = subprocess.Popen(
                                    ["bash", "start_iphone.sh"], cwd=ROOT,
                                    stdin=subprocess.DEVNULL, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True,
                                )
                            end = time.monotonic() + window_seconds
                            outcome = "HOLD_TIMEOUT_ALIVE"
                            while time.monotonic() < end:
                                if owner_http_ok():
                                    outcome = "READY_SPAWNED"
                                    break
                                polled = child.poll()
                                if polled is not None:
                                    child_exit_code = polled
                                    outcome = "FAIL_CHILD_EXITED"
                                    break
                                time.sleep(poll_seconds)
                            if outcome == "HOLD_TIMEOUT_ALIVE":
                                polled = child.poll()
                                if polled is not None:
                                    child_exit_code = polled
                                    outcome = "FAIL_TIMEOUT_EXITED"
                except OSError:
                    outcome = "FAIL_SPAWN"
            write_event(outcome, exit_code=child_exit_code)
            return outcome
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def read_receipt() -> dict[str, object]:
    """Pure READ: never treat stale recorded READY as actual current health."""
    try:
        if STORAGE.is_symlink() or RECEIPT.is_symlink():
            return {"receipt": "UNSAFE", "exit_code": None}
        info = RECEIPT.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 2048):
            return {"receipt": "UNSAFE", "exit_code": None}
        data = json.loads(RECEIPT.read_text(encoding="utf-8"))
        value = data.get("state") if isinstance(data, dict) else None
        if value not in KNOWN_CODES:
            return {"receipt": "UNKNOWN", "exit_code": None}
        ec = data.get("exit_code")
        return {"receipt": value, "exit_code": ec if type(ec) is int and 0 <= ec <= 255 else None}
    except (OSError, ValueError, TypeError):
        return {"receipt": "UNKNOWN", "exit_code": None}


def status_only() -> int:
    receipt = read_receipt()
    ready = owner_http_ok()  # Current observation is independent of stored history.
    print(json.dumps({"event":"BOOT_STATUS", **receipt, "http_ready_now":ready,
                      "port_8000_open_now":port_open()}, sort_keys=True))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ensure", action="store_true", help="One guarded server launch (devcontainer postStart only)")
    mode.add_argument("--status", action="store_true", help="Read-only fixed receipt and current localhost status")
    p.add_argument("--window-seconds", type=float, default=16.0)
    args = p.parse_args()
    if args.status:
        return status_only()
    if not 1 <= args.window_seconds <= 30:
        p.error("invalid check window")
    result = start_once(args.window_seconds)
    if result in ("READY_ALREADY", "READY_SPAWNED"):
        return 0
    if result.startswith("HOLD_"):
        print("MINIFISH_API_BOOT=" + result) if result in ("HOLD_NOT_CODESPACE", "HOLD_SOURCE_MISMATCH", "HOLD_SOURCE_READ_ERROR", "HOLD_PRIVATE_PORTS", "HOLD_PRIVATE_DIRECTORY", "HOLD_LOCK_BUSY") else None
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
