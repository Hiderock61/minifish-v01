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
from time import monotonic
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


STOP_REASONS = frozenset(("UNSPECIFIED", "OWNER_CANCELLED", "WAIT_TIMEOUT",
    "BROWSER_CLOSED", "URL_NOT_ALLOWED", "HTTP_NO_RESPONSE", "HTTP_401",
    "HTTP_403", "HTTP_429", "HTTP_ERROR", "LOGIN_PAGE_NOT_FINISHED"))


class _StopWithoutSaving(Exception):
    def __init__(self, reason="UNSPECIFIED"):
        super().__init__(reason if reason in STOP_REASONS else "UNSPECIFIED")


class OwnerLoginHandoff:
    def __init__(self):
        self._lock = Lock()
        self._worker: Thread | None = None
        self._finish = Event()
        self._cancel = Event()
        self._status = "LOGIN_NOT_STARTED"
        self._stop_reason = "NONE"
        self._navigation_http = 0
        self._navigation_allowed = False

    def status(self) -> dict[str, object]:
        with self._lock:
            busy = self._worker is not None and self._worker.is_alive()
            return {
                "site": SITE,
                "status": self._status,
                "busy": busy,
                "stop_reason": self._stop_reason,
                "navigation_http": self._navigation_http,
                "navigation_url_allowed": self._navigation_allowed,
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
            self._stop_reason = "NONE"
            self._navigation_http = 0
            self._navigation_allowed = False
            self._worker = Thread(
                target=self._run, args=(check_saved, self._finish, self._cancel), daemon=True
            )
            self._worker.start()

    def finish(self) -> None:
        with self._lock:
            # A repeated request after acceptance must not save twice or
            # turn a completed save into a misleading HTTP conflict.
            if self._status in ("SAVING_SESSION", "SESSION_SAVED_LOGIN_UNVERIFIED"):
                return
            if (self._worker is None or not self._worker.is_alive()
                    or self._status not in ("WAITING_FOR_HUMAN",
                                           "SESSION_REOPENED_LOGIN_NOT_VERIFIED")):
                raise ValueError("LOGIN_NOT_READY")
            self._status = "SAVING_SESSION"
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

    def _record_navigation(self, status, url):
        with self._lock:
            self._navigation_http = status if isinstance(status, int) else 0
            self._navigation_allowed = _approved_url(url)

    def _record_response(self, response, page):
        request = response.request
        if request.is_navigation_request() and request.frame == page.main_frame:
            self._record_navigation(response.status, response.url)

    def _wait_for_owner(self, page, finish, cancel):
        deadline = monotonic() + WAIT_SECONDS
        while not finish.is_set():
            if cancel.is_set():
                raise _StopWithoutSaving("OWNER_CANCELLED")
            if page.is_closed():
                raise _StopWithoutSaving("BROWSER_CLOSED")
            if monotonic() >= deadline:
                raise _StopWithoutSaving("WAIT_TIMEOUT")
            # Playwright's wait pumps route/response callbacks from manual UI
            # input. threading.Event.wait blocks this worker's event dispatch.
            page.wait_for_timeout(200)
            if not _approved_url(page.url):
                raise _StopWithoutSaving("URL_NOT_ALLOWED")
            with self._lock:
                status = self._navigation_http
            self._check_http(status)
        if cancel.is_set():
            raise _StopWithoutSaving("OWNER_CANCELLED")

    @staticmethod
    def _check_http(status):
        if not status:
            raise _StopWithoutSaving("HTTP_NO_RESPONSE")
        if status in (401, 403, 429):
            raise _StopWithoutSaving("HTTP_" + str(status))
        if status >= 400:
            raise _StopWithoutSaving("HTTP_ERROR")

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
                browser.page.on("response", lambda response:
                    self._record_response(response, browser.page))
                response = browser.page.goto(
                    HOME_URL if check_saved else LOGIN_URL,
                    timeout=20000, wait_until="domcontentloaded"
                )
                self._record_navigation(response.status if response else 0, browser.current_url)
                if not _approved_url(browser.current_url):
                    raise _StopWithoutSaving("URL_NOT_ALLOWED")
                self._check_http(response.status if response else 0)
                if check_saved:
                    # Page navigation works; authentication still requires
                    # owner-side verification of the actual account screen.
                    self._set("SESSION_REOPENED_LOGIN_NOT_VERIFIED")
                else:
                    self._set("WAITING_FOR_HUMAN")
                # Browser GUI remains interactive; no Playwright auto clicks.
                # Worker never reads the password field or submits login.
                self._wait_for_owner(browser.page, finish, cancel)
                stage = "SESSION_SAVE"
                current = urlsplit(browser.current_url)
                if not _approved_url(browser.current_url) or (
                    current.path.rstrip("/") in ("/login", "/users/sign_in")
                ):
                    raise _StopWithoutSaving("LOGIN_PAGE_NOT_FINISHED")
                # Save only after owner pressed "ログイン完了" and navigated
                # away from the login path. Still not proof of login.
                # PlaywrightBrowser.__exit__ encrypts the state.
            self._set("SESSION_SAVED_LOGIN_UNVERIFIED")
        except _StopWithoutSaving as stopped:
            with self._lock:
                self._stop_reason = str(stopped)
            self._set("STOPPED_NO_AUTH_ASSERTION")
        except Exception:
            # No exception text or page contents returned to the dashboard.
            self._set("BLOCKED_" + stage)


handoff = OwnerLoginHandoff()
