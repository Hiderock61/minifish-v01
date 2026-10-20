"""Owner-only CrowdWorks login handoff for private MiniFish desktop.

This does not log in, enter credentials, or submit anything automatically.
A human must manually interact with a private Chromium screen; the worker
only starts the browser, waits for explicit finish, encrypts storage state,
and reports fixed status codes. No credentials or page text in logs.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

from .browser import PlaywrightBrowser
from .session_vault import EncryptedSessionVault

SITE = "crowdworks"
LOGIN_URL = "https://crowdworks.jp/login"
HOME_URL = "https://crowdworks.jp/"
WAIT_SECONDS = 900
ROOT = Path.home() / ".local" / "share" / "minifish" / "owner-sessions"


def _approved_url(url: str) -> bool:
    """Only owner-authorized site and its subdomains in top-level navigation."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        return (
            parsed.scheme == "https"
            and (hostname == "crowdworks.jp" or hostname.endswith(".crowdworks.jp"))
            and parsed.port is None
            and parsed.username is None and parsed.password is None
        )
    except ValueError:
        return False


def _browser_route(route) -> None:
    """Block top-level navigation outside CrowdWorks; never bypass 403/429."""
    req = route.request
    if req.is_navigation_request() and req.frame == req.frame.page.main_frame:
        if not _approved_url(req.url):
            route.abort()
            return
    route.continue_()


def _secret_vault() -> EncryptedSessionVault:
    """Private OS-user-only storage. The key never goes to GitHub or logs."""
    root = ROOT
    if root.is_symlink():
        raise ValueError("CROWDWORKS_ROOT_SYMLINK")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError("CROWDWORKS_ROOT_PERMISSIONS")
    keypath = root / "crowdworks.key"
    if keypath.is_symlink():
        raise ValueError("CROWDWORKS_KEY_SYMLINK")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(keypath, flags)
    except FileNotFoundError:
        try:
            fd = os.open(keypath, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as writer:
                writer.write(Fernet.generate_key())
        except FileExistsError:
            pass
        fd = os.open(keypath, flags)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600:
            raise ValueError("CROWDWORKS_KEY_PERMISSIONS")
        with os.fdopen(fd, "rb") as reader:
            fd = -1
            key = reader.read(64)
    finally:
        if fd >= 0:
            os.close(fd)
    return EncryptedSessionVault(root / "crowdworks.vault", key)


class _StopWithoutSaving(Exception):
    pass


class OwnerLoginHandoff:
    def __init__(self):
        self._lock = Lock()
        self._worker: Thread | None = None
        self._finish = Event()
        self._cancel = Event()
        self._status = "LOGIN_NOT_STARTED"

    def status(self) -> dict[str, object]:
        with self._lock:
            busy = self._worker is not None and self._worker.is_alive()
            return {
                "site": SITE,
                "status": self._status,
                "busy": busy,
                "credentials_collected_by_minifish": False,
                "external_submission_by_minifish": False,
                "login_verified": False,
            }

    def _set(self, new_state: str) -> None:
        with self._lock:
            self._status = new_state

    def launch(self, *, check_saved: bool = False) -> None:
        if not os.getenv("CODESPACE_NAME"):
            raise ValueError("PRIVATE_CODESPACE_REQUIRED")
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ValueError("LOGIN_ALREADY_RUNNING")
            self._finish = Event()
            self._cancel = Event()
            self._status = "OPENING_PRIVATE_BROWSER"
            self._worker = Thread(
                target=self._run, args=(check_saved, self._finish, self._cancel), daemon=True
            )
            self._worker.start()

    def finish(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive() or self._status != "WAITING_FOR_HUMAN":
                raise ValueError("LOGIN_NOT_READY")
            self._finish.set()

    def cancel(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                raise ValueError("LOGIN_NOT_RUNNING")
            self._cancel.set()

    def revoke(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ValueError("LOGIN_RUNNING_CANNOT_REVOKE")
        vault = _secret_vault()
        if vault.path.exists():
            vault.path.unlink()
        self._set("LOCAL_SESSION_REVOKED")

    def _run(self, check_saved: bool, finish: Event, cancel: Event) -> None:
        stage = "PRIVATE_BROWSER"
        try:
            vault = _secret_vault()
            if check_saved and vault.load() is None:
                self._set("NO_SAVED_SESSION")
                return
            # Never configure screenshots, recordings or raw profile logging.
            with PlaywrightBrowser(headless=False, profile_path=None,
                                   capture_dir=None, session_vault=vault) as browser:
                assert browser.context is not None and browser.page is not None
                browser.context.route("**/*", _browser_route)
                stage = "LOGIN_PAGE"
                response = browser.page.goto(
                    HOME_URL if check_saved else LOGIN_URL,
                    timeout=20000, wait_until="domcontentloaded"
                )
                if not _approved_url(browser.current_url):
                    raise _StopWithoutSaving()
                if response is None or response.status in (401, 403, 429) or response.status >= 400:
                    raise _StopWithoutSaving()
                if check_saved:
                    # Page navigation works; authentication still requires
                    # owner-side verification of the actual account screen.
                    self._set("SESSION_REOPENED_LOGIN_NOT_VERIFIED")
                    return
                self._set("WAITING_FOR_HUMAN")
                # Browser GUI remains interactive; no Playwright auto clicks.
                # Worker never reads the password field or submits login.
                from time import monotonic
                deadline = monotonic() + WAIT_SECONDS
                while not finish.wait(0.2):
                    if cancel.is_set() or monotonic() >= deadline:
                        raise _StopWithoutSaving()
                if cancel.is_set():
                    raise _StopWithoutSaving()
                stage = "SESSION_SAVE"
                current = urlsplit(browser.current_url)
                if not _approved_url(browser.current_url) or (
                    current.path.rstrip("/") in ("/login", "/users/sign_in")
                ):
                    raise _StopWithoutSaving()
                # Save only after owner pressed "ログイン完了" and navigated
                # away from the login path. Still not proof of login.
                # PlaywrightBrowser.__exit__ encrypts the state.
            self._set("SESSION_SAVED_LOGIN_UNVERIFIED")
        except _StopWithoutSaving:
            self._set("STOPPED_NO_AUTH_ASSERTION")
        except Exception:
            # No exception text or page contents returned to the dashboard.
            self._set("BLOCKED_" + stage)


handoff = OwnerLoginHandoff()
