#!/usr/bin/env python3
"""MiniFish Private noVNC visual acceptance without secret disclosure.

Runs only inside one approved Codespace and only against localhost. --check
is read-only. --connect deliberately authenticates a local headless noVNC
client using the existing private VNC secret, and closes the client afterward.
No owner Runtime POST, external site navigation, session export or new server.
Never emit secret, page content, request/response body, JS console or traceback.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

EXPECTED = "accursed-apparition-6q7jwqq5965h4rpq"
HOME = Path.home()
ROOT = HOME / ".local/share/minifish"
PRIVATE = ROOT / "g1b-mock-only"
SECRET = PRIVATE / "vnc-password.txt"
SNAPSHOT = PRIVATE / "novnc-auth-verified.png"
OWNER_PORTS = ((6081, "/vnc.html"), (8002, "/login-ready"))
OPENER = build_opener(ProxyHandler({}))
STATUS_OK = frozenset(("GATE_READY", "NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE",
                       "NOVNC_LOCAL_AUTH_PASS_CANVAS_PENDING"))


class Hold(Exception):
    """Known, nonsecret diagnosis code only."""


def emit(verdict: str, **fields: object) -> None:
    print(json.dumps({"event": "NOVNC_LOCAL_ACCEPTANCE", "verdict": verdict,
                      "secret_disclosed": False, "owner_post_count": 0,
                      "credential_logged": False, **fields},
                     ensure_ascii=False, sort_keys=True), flush=True)


def safe_stat(path: Path, required_mode: int, directory: bool) -> None:
    try:
        meta = path.lstat()
    except OSError:
        raise Hold("HOLD_PRIVATE_PATH_UNAVAILABLE") from None
    if (stat.S_ISLNK(meta.st_mode) or meta.st_uid != os.geteuid()
            or stat.S_IMODE(meta.st_mode) != required_mode):
        raise Hold("HOLD_PRIVATE_PATH_UNSAFE")
    if directory and not stat.S_ISDIR(meta.st_mode):
        raise Hold("HOLD_PRIVATE_PATH_UNSAFE")
    if not directory and not stat.S_ISREG(meta.st_mode):
        raise Hold("HOLD_PRIVATE_PATH_UNSAFE")


def file_guard() -> None:
    # Do not allow symlinks in any ancestor between HOME and private file.
    for path in (HOME, HOME / ".local", HOME / ".local/share"):
        try:
            meta = path.lstat()
            if not stat.S_ISDIR(meta.st_mode) or stat.S_ISLNK(meta.st_mode):
                raise Hold("HOLD_ANCESTOR_UNSAFE")
        except OSError:
            raise Hold("HOLD_ANCESTOR_UNSAFE") from None
    safe_stat(ROOT, 0o700, True)
    safe_stat(PRIVATE, 0o700, True)
    safe_stat(SECRET, 0o600, False)


def read_secret() -> str:
    file_guard()
    fd = -1
    try:
        fd = os.open(SECRET, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_size != 8):
            raise Hold("HOLD_SECRET_FILE_UNSAFE")
        raw = os.read(fd, 16)
        if len(raw) != 8:
            raise Hold("HOLD_SECRET_FILE_UNSAFE")
        try:
            value = raw.decode("ascii")
        except UnicodeError:
            raise Hold("HOLD_SECRET_FILE_UNSAFE") from None
        if re.fullmatch(r"[A-Za-z0-9]{8}", value) is None:
            raise Hold("HOLD_SECRET_FILE_UNSAFE")
        return value
    except OSError:
        raise Hold("HOLD_SECRET_FILE_UNREADABLE") from None
    finally:
        if fd >= 0:
            os.close(fd)


def tcp_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def http_ready(port: int, path: str) -> bool:
    if (port, path) not in OWNER_PORTS:
        return False
    try:
        with OPENER.open(Request(f"http://127.0.0.1:{port}{path}",
                                 method="GET"), timeout=3) as resp:
            return resp.status == 200
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def gate() -> None:
    if os.getenv("CODESPACE_NAME") != EXPECTED:
        raise Hold("HOLD_WRONG_CODESPACE")
    file_guard()
    if not tcp_ready(5911) or not all(http_ready(*item) for item in OWNER_PORTS):
        raise Hold("HOLD_RUNTIME_NOT_READY")


def local_only(route) -> None:
    """No third-party URL loads in this inspection browser."""
    url = route.request.url
    if url.startswith("http://127.0.0.1:6081/"):
        route.continue_()
    else:
        route.abort()


def connected_state(page) -> bool:
    """noVNC exposes a connected state on its root element."""
    return bool(page.evaluate("""() => {
      const root=document.documentElement;
      const stat=document.querySelector('#noVNC_status')?.textContent || '';
      return root.classList.contains('noVNC_connected') ||
        (/\\bconnected\\b/i.test(stat) && !/disconnected/i.test(stat));
    }"""))


def connect(*, snapshot: bool = False) -> str:
    gate()
    # Read the private secret into this process only; do not print it.
    password = read_secret()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Hold("HOLD_PLAYWRIGHT_UNAVAILABLE") from None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[
                "--no-sandbox", "--disable-background-networking",
                "--disable-component-update", "--disable-sync",
            ])
            try:
                context = browser.new_context(service_workers="block",
                                               accept_downloads=False)
                page = context.new_page()
                page.route("**/*", local_only)
                page.goto("http://127.0.0.1:6081/vnc.html",
                          wait_until="domcontentloaded", timeout=12000)
                field = page.locator("#noVNC_password_input")
                if not field.is_visible():
                    page.locator("#noVNC_connect_button").click(timeout=8000)
                field.wait_for(state="visible", timeout=10000)
                field.fill(password, timeout=5000)
                page.locator("#noVNC_credentials_button").click(timeout=5000)
                # Never read password input again or display page contents.
                page.wait_for_function("""() => {
                  const root=document.documentElement;
                  const t=document.querySelector('#noVNC_status')?.textContent || '';
                  return root.classList.contains('noVNC_connected') ||
                    (/\\bconnected\\b/i.test(t) && !/disconnected/i.test(t));
                }""", timeout=18000)
                canvas_visible = page.locator("#noVNC_container canvas").count() > 0
                if canvas_visible:
                    canvas_visible = page.locator("#noVNC_container canvas").first.is_visible()
                verdict = ("NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE" if canvas_visible
                           else "NOVNC_LOCAL_AUTH_PASS_CANVAS_PENDING")
                if snapshot and canvas_visible:
                    save_snapshot(page)
                return verdict
            finally:
                browser.close()
    except Hold:
        raise
    except Exception:
        # A Playwright error may include URL, HTTP headers or input value:
        # never serialize it, even in development logs.
        raise Hold("HOLD_NOVNC_UI_OR_AUTH_UNCONFIRMED") from None


def save_snapshot(page) -> None:
    """Optional screenshot stays inside private 0700 directory, mode 0600."""
    if SNAPSHOT.is_symlink():
        raise Hold("HOLD_SNAPSHOT_DEST_UNSAFE")
    file_guard()
    fd, tmp = tempfile.mkstemp(prefix=".novnc-check-", suffix=".png", dir=PRIVATE)
    try:
        os.close(fd)
        os.chmod(tmp, 0o600)
        page.screenshot(path=tmp, animations="disabled", timeout=6000)
        # Never write screenshot if an unexpected destination already exists.
        if SNAPSHOT.exists():
            raise Hold("HOLD_SNAPSHOT_DEST_EXISTS")
        os.replace(tmp, SNAPSHOT)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Read-only safety and local port gate")
    mode.add_argument("--connect", action="store_true", help="One local noVNC authentication attempt")
    p.add_argument("--snapshot-private", action="store_true",
                   help="Save a screenshot only after noVNC connects; never upload automatically")
    args = p.parse_args(argv)
    if args.snapshot_private and not args.connect:
        p.error("--snapshot-private requires --connect")
    try:
        if args.check:
            gate()
            result = "GATE_READY"
        else:
            result = connect(snapshot=args.snapshot_private)
        emit(result, canvas_visible=(result == "NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE"),
             snapshot_requested=args.snapshot_private)
        return 0 if result in STATUS_OK else 2
    except Hold as e:
        emit(str(e), snapshot_requested=args.snapshot_private)
        return 2


if __name__ == "__main__":
    sys.exit(main())
