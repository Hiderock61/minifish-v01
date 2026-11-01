#!/usr/bin/env python3
"""Read-only, secret-free owner Chromium X11/hand-off status inspection.

Reads local X11 window metadata and localhost:8002 fixed owner status.
Never captures pixels, prints titles or process arguments, changes browser,
reads VNC passwords, sends POST, or makes an external network request.

An X11 mapped Chromium window and WAITING_FOR_HUMAN support the claim
"Chromium window mapped & CrowdWorks navigation completed in controller".
They DO NOT prove a human visually read the page's pixels.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CODESPACE = "accursed-apparition-6q7jwqq5965h4rpq"
ROOT = Path("/workspaces/minifish-v01")
HOME = Path.home()
PARENT = HOME / ".local/share/minifish"
EXPECTED_BLOBS = {
    "minifish/crowdworks_handoff.py": "9da6a807df46093ca42d9f60201e3657cb472470",
    "g1b_mock_app.py": "d8ae3f8de50159022876e500d29930d5422380d6",
}
STATES = frozenset(("LOGIN_NOT_STARTED", "OPENING_PRIVATE_BROWSER", "WAITING_FOR_HUMAN",
    "STOPPED_NO_AUTH_ASSERTION", "BLOCKED_PRIVATE_BROWSER", "BLOCKED_LOGIN_PAGE",
    "SESSION_SAVED_LOGIN_UNVERIFIED", "SESSION_REOPENED_LOGIN_NOT_VERIFIED",
    "NO_SAVED_SESSION"))
MAX_WINDOWS = 40
OPENER = build_opener(ProxyHandler({}), HTTPRedirectHandler())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


class Hold(Exception):
    pass


def emit(verdict: str, **data: object) -> None:
    print(json.dumps({"event":"CHROMIUM_GUI_READ", "verdict":verdict,
                      "owner_post_count":0, "browser_action_count":0,
                      "screenshot_export_count":0, "secret_exposed":False,
                      **data}, sort_keys=True, ensure_ascii=False), flush=True)


def git_blob(path: Path) -> str:
    # The exact source code that determines when WAITING_FOR_HUMAN is emitted.
    raw = path.read_bytes()
    if len(raw) > 160000:
        raise Hold("HOLD_SOURCE_TOO_LARGE")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def gate() -> None:
    if os.getenv("CODESPACE_NAME") != CODESPACE:
        raise Hold("HOLD_WRONG_CODESPACE")
    for path, sha in EXPECTED_BLOBS.items():
        try:
            if git_blob(ROOT / path) != sha:
                raise Hold("HOLD_SOURCE_CHANGED")
        except OSError:
            raise Hold("HOLD_SOURCE_UNAVAILABLE") from None
    try:
        m = PARENT.lstat()
    except OSError:
        raise Hold("HOLD_PRIVATE_ROOT_UNKNOWN") from None
    if (not stat.S_ISDIR(m.st_mode) or stat.S_ISLNK(m.st_mode)
            or m.st_uid != os.geteuid() or stat.S_IMODE(m.st_mode) != 0o700):
        raise Hold("HOLD_PRIVATE_ROOT_UNSAFE")


def owner_status() -> str:
    req = Request("http://127.0.0.1:8002/g1/owner/status", method="GET",
                  headers={"Cache-Control":"no-store", "Accept":"application/json"})
    try:
        with OPENER.open(req, timeout=3) as resp:
            if resp.status != 200:
                raise Hold("HOLD_STATUS_HTTP")
            raw = resp.read(4097)
    except (HTTPError, URLError, OSError, TimeoutError):
        raise Hold("HOLD_STATUS_UNAVAILABLE") from None
    if len(raw) > 4096:
        raise Hold("HOLD_STATUS_TOO_LARGE")
    try:
        data = json.loads(raw)
        status = data.get("status")
        return status if isinstance(status, str) and status in STATES else "STATUS_UNKNOWN"
    except (UnicodeError, ValueError, AttributeError):
        return "STATUS_UNKNOWN"
    # DO NOT serialize the response. It may contain an action_nonce.


def run_cmd(args: list[str]) -> str:
    try:
        proc = subprocess.run(args, env={**os.environ, "DISPLAY":":11"},
                              capture_output=True, text=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Hold("HOLD_X11_QUERY_UNAVAILABLE") from None
    if proc.returncode != 0 or len(proc.stdout) > 24000:
        raise Hold("HOLD_X11_QUERY_FAILED")
    return proc.stdout


def windows() -> list[str]:
    if not shutil.which("xprop") or not shutil.which("xwininfo"):
        raise Hold("HOLD_X11_UTILITIES_MISSING")
    text = run_cmd(["xprop", "-root", "_NET_CLIENT_LIST"])
    ids = list(dict.fromkeys(re.findall(r"0x[0-9a-fA-F]{1,8}", text)))
    return ids[:MAX_WINDOWS]


def is_chromium_class(raw: str) -> bool:
    # No printing of raw text: WM_CLASS could theoretically contain secret.
    lines = [line for line in raw.splitlines() if line.startswith("WM_CLASS(")]
    return any(re.search(r"(?i)\b(chromium|google-chrome|chrome-browser)\b", line)
               for line in lines)


def read_pid(raw: str) -> int | None:
    match = re.search(r"_NET_WM_PID\([^)]*\)\s*=\s*(\d+)\s*(?:$|\n)", raw)
    if not match:
        return None
    pid = int(match.group(1))
    return pid if pid > 1 else None


def owned_chromium(pid: int, proc_root: Path = Path("/proc")) -> bool:
    try:
        info = (proc_root / str(pid) / "status").read_text(encoding="ascii", errors="replace")
        uid = next((int(s.split()[2]) for s in info.splitlines() if s.startswith("Uid:")), None)
        name = (proc_root / str(pid) / "comm").read_text(encoding="ascii", errors="replace").strip().lower()
    except (OSError, ValueError, IndexError):
        return False
    return uid == os.geteuid() and (name.startswith("chrome") or name.startswith("chromium"))


def window_viewable(raw: str) -> bool:
    match = re.search(r"Map State:\s*IsViewable\b", raw)
    width = re.search(r"\bWidth:\s*(\d+)", raw)
    height = re.search(r"\bHeight:\s*(\d+)", raw)
    return bool(match and width and height
                and int(width.group(1)) >= 320 and int(height.group(1)) >= 240)


def inspect() -> tuple[str, dict[str, object]]:
    gate()
    state = owner_status()
    ids = windows()
    chromium_class = False
    mapped = False
    pid_verified = False
    count = 0
    for win in ids:
        # IDs come only from bounded xprop's 0xHEX window list.
        try:
            props = run_cmd(["xprop", "-id", win, "WM_CLASS", "_NET_WM_PID"])
            if not is_chromium_class(props):
                continue
            chromium_class = True
            pid = read_pid(props)
            if pid is None or not owned_chromium(pid):
                continue
            pid_verified = True
            view = run_cmd(["xwininfo", "-id", win, "-stats"])
            if window_viewable(view):
                mapped = True
                count += 1
        except Hold:
            continue
    fields = {"owner_status": state, "x11_window_count_bounded": len(ids),
              "chromium_class_seen": chromium_class,
              "chromium_pid_owner_verified": pid_verified,
              "chromium_mapped_viewable": mapped,
              "chromium_visible_window_count": count,
              "real_page_pixels_inspected": False}
    if mapped and state == "WAITING_FOR_HUMAN":
        verdict = "CHROMIUM_WINDOW_MAPPED_LOGIN_NAVIGATION_COMPLETE_PIXELS_UNVERIFIED"
    elif mapped:
        verdict = "CHROMIUM_WINDOW_MAPPED_LOGIN_STATE_UNCONFIRMED"
    elif state == "WAITING_FOR_HUMAN":
        verdict = "LOGIN_NAVIGATION_COMPLETE_X11_WINDOW_UNCONFIRMED"
    else:
        verdict = "HOLD_BROWSER_SCREEN_NOT_CONFIRMED"
    return verdict, fields


def main() -> int:
    try:
        verdict, fields = inspect()
        emit(verdict, **fields)
        return 0 if verdict.startswith("CHROMIUM_WINDOW_MAPPED_LOGIN_NAVIGATION") else 2
    except Hold as e:
        emit(str(e))
        return 2
    except Exception:
        # Never expose raw X11/HTTP errors which may embed window titles.
        emit("HOLD_INSPECTION_UNKNOWN")
        return 2


if __name__ == "__main__":
    sys.exit(main())
