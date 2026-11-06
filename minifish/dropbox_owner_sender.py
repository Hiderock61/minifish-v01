"""Owner-only one-shot synthetic Dropbox File Request sender.

This module is NEVER dispatched from public GitHub Issues or Actions.
The actual File Request upload URL is read only from a private owner-side
environment variable. It is not printed, logged, committed, or returned.
Only a fixed synthetic text file can be transmitted. No user files, cookies,
CrowdWorks credentials or encrypted owner Vault are accessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import json
import os
import re
import stat

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from .dropbox_upload_mock import FILE_BODY

_PROBE_FILE = "minifish_owner_probe_20261107.txt"
_PROBE_BODY = b"MINIFISH_OWNER_AUTO_SYNTHETIC_ONLY\nRESULT=MOCK_ONLY\n"
_REQUEST_PATH = re.compile(r"/request/[A-Za-z0-9_-]{10,64}/?\Z")
_ALLOWED_ASSET_HOSTS = frozenset((
    "www.dropbox.com",
    "dropbox.com",
    "api.dropboxapi.com",
    "content.dropboxapi.com",
))
_PROBE_DIR = Path.home() / ".local" / "share" / "minifish" / "owner-dropbox-probe"
_MARKER_NAME = "upload-one-shot-v1.attempted"
_APPROVED_ENV = "MINIFISH_OWNER_DROPBOX_PROBE_APPROVED"
_URL_ENV = "MINIFISH_PRIVATE_DROPBOX_REQUEST_URL"


def _validate_live_url(url: str) -> None:
    try:
        p = urlsplit(url)
        accepted = (
            p.scheme == "https" and p.hostname == "www.dropbox.com"
            and p.port is None and p.username is None and p.password is None
            and not p.query and not p.fragment
            and bool(_REQUEST_PATH.fullmatch(p.path))
        )
    except (TypeError, ValueError):
        accepted = False
    if not accepted:
        raise ValueError("DROPBOX_REQUEST_URL_NOT_APPROVED")


def _validate_local_test(url: str) -> int:
    if (os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") != "1"
            or "PYTEST_CURRENT_TEST" not in os.environ
            or os.getenv("CODESPACE_NAME")):
        raise ValueError("LOCAL_UPLOAD_MOCK_DISABLED")
    try:
        p = urlsplit(url)
        accepted = (
            p.scheme == "http" and p.hostname == "127.0.0.1"
            and p.port is not None and p.port > 0
            and p.username is None and p.password is None
            and p.path == "/request" and not p.query and not p.fragment
        )
    except (TypeError, ValueError):
        accepted = False
    if not accepted:
        raise ValueError("LOCAL_UPLOAD_MOCK_URL_INVALID")
    return p.port


def _can_route(url: str, method: str, *, local_port: int | None = None,
               main_navigation: bool = False) -> bool:
    """Deny arbitrary external hosts, local networks and other protocols."""
    try:
        p = urlsplit(url)
        if p.username is not None or p.password is not None:
            return False
        if local_port is not None:
            return (
                p.scheme == "http" and p.hostname == "127.0.0.1"
                and p.port == local_port and not p.query and not p.fragment
                and ((method == "GET" and p.path == "/request")
                     or (method == "POST" and p.path == "/upload"))
            )
        if p.scheme != "https" or p.port is not None:
            return False
        host = p.hostname or ""
        if main_navigation:
            return (method == "GET" and host == "www.dropbox.com"
                    and bool(_REQUEST_PATH.fullmatch(p.path)))
        if host in _ALLOWED_ASSET_HOSTS or host.endswith(".dropboxstatic.com"):
            return method in ("GET", "POST", "PUT") and (
                method == "GET" or host != "dropbox.com"
            )
        return False
    except ValueError:
        return False


def _mark_attempt(dir_path: Path) -> None:
    """Reserve at most one real attempt, even on timeout/ambiguous outcome.

    The caller must treat the marker as permanent until manually reviewed.
    It deliberately contains NO URL, account identifier or file contents.
    """
    if dir_path.is_symlink():
        raise ValueError("OWNER_PROBE_DIR_SYMLINK")
    dir_path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(dir_path.stat().st_mode) != 0o700:
        raise ValueError("OWNER_PROBE_DIR_PERMISSIONS")
    marker = dir_path / _MARKER_NAME
    if marker.is_symlink():
        raise ValueError("OWNER_PROBE_MARKER_SYMLINK")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(marker, flags, 0o600)
    except FileExistsError:
        raise ValueError("OWNER_PROBE_ALREADY_ATTEMPTED") from None
    with os.fdopen(fd, "wb") as writer:
        writer.write(b"ATTEMPTED\n")


@dataclass(frozen=True)
class OwnerUploadReceipt:
    status: str
    attempted: bool
    local_test: bool

    def public_receipt(self) -> dict[str, object]:
        return {
            "mode": "owner_synthetic_dropbox_probe",
            "status": self.status,
            "attempted": self.attempted,
            "local_test": self.local_test,
            "secret_values_included": False,
            "private_page_data_included": False,
            "real_account_data_uploaded": False,
        }


def run_owner_probe(*, local_test_url: str | None = None,
                    marker_dir: Path | None = None) -> OwnerUploadReceipt:
    """Attempt exactly one synthetic upload. Always verify actual receipt outside.

    Live path requires private Codespace AND an independent owner-approval
    environment flag. Never provides a public GitHub Issue dispatch route.
    The test path can only target an isolated localhost fake receiver.
    """
    test_mode = local_test_url is not None
    if test_mode:
        url = local_test_url
        port = _validate_local_test(url)
        if marker_dir is None:
            raise ValueError("LOCAL_UPLOAD_TEST_MARKER_REQUIRED")
    else:
        if (not os.getenv("CODESPACE_NAME")
                or os.getenv(_APPROVED_ENV) != "1"
                or "PYTEST_CURRENT_TEST" in os.environ):
            raise ValueError("OWNER_DROPBOX_PROBE_NOT_AUTHORIZED")
        url = os.getenv(_URL_ENV, "")
        _validate_live_url(url)
        port = None
        if marker_dir is not None:
            raise ValueError("OWNER_PROBE_MARKER_OVERRIDE_FORBIDDEN")
        marker_dir = _PROBE_DIR

    _mark_attempt(marker_dir)
    status = "STOP_NOT_SUBMITTED"
    attempted = False
    try:
        with TemporaryDirectory(prefix="minifish-synthetic-sender-") as tmp:
            path = Path(tmp) / _PROBE_FILE
            path.write_bytes(_PROBE_BODY)
            path.chmod(0o600)

            with sync_playwright() as pw:
                browser = None
                try:
                    kwargs = {"headless": True, "args": ["--no-sandbox"]}
                    if os.getenv("MINIFISH_CHROMIUM_PATH"):
                        kwargs["executable_path"] = os.environ["MINIFISH_CHROMIUM_PATH"]
                    browser = pw.chromium.launch(**kwargs)
                    context = browser.new_context(
                        service_workers="block", accept_downloads=False,
                    )
                    context.set_default_timeout(8000)

                    def only_approved_requests(route):
                        req = route.request
                        try:
                            main = req.is_navigation_request() and (
                                req.frame == req.frame.page.main_frame
                            )
                        except Exception:
                            main = False
                        if _can_route(req.url, req.method, local_port=port,
                                      main_navigation=main):
                            route.continue_()
                        else:
                            route.abort()

                    context.route("**/*", only_approved_requests)
                    page = context.new_page()
                    nav = page.goto(
                        url, wait_until="domcontentloaded", timeout=20000,
                    )
                    if nav is None or nav.status >= 400:
                        return OwnerUploadReceipt("STOP_PAGE_UNAVAILABLE", False, test_mode)
                    selector = page.locator('input[type="file"]')
                    if selector.count() != 1:
                        return OwnerUploadReceipt("STOP_FILE_INPUT_NOT_UNIQUE", False, test_mode)
                    selector.set_input_files(str(path), timeout=8000)

                    # Click only an unambiguous upload/submit button.
                    if test_mode:
                        button = page.get_by_role(
                            "button", name="Send synthetic file", exact=True,
                        )
                    else:
                        button = page.get_by_role(
                            "button",
                            name=re.compile(r"^(Upload|アップロード|Send files|ファイルを送信)(?:\s*\(\d+\))?$", re.I),
                        )
                    if button.count() != 1:
                        return OwnerUploadReceipt("STOP_UPLOAD_BUTTON_UNCLEAR", False, test_mode)
                    attempted = True
                    button.click(timeout=8000)
                    if test_mode:
                        page.locator("#result").wait_for(timeout=7000)
                        if page.locator("#result").inner_text() != "SYNTHETIC_UPLOAD_OK":
                            return OwnerUploadReceipt("STOP_MOCK_RECEIVER_REJECTED", attempted, True)
                        status = "MOCK_UPLOAD_PASS"
                    else:
                        # The final PASS can only be decided by Dropbox
                        # authenticated Inbox LIST+READ, not by a page claim.
                        status = "SUBMISSION_ATTEMPTED_UNVERIFIED"
                finally:
                    if browser is not None:
                        browser.close()
    except (PlaywrightTimeout, Exception):
        # Fail closed with no URL/cookie/page/exception text printed or logged.
        status = "STOP_BROWSER_OR_NETWORK"
    return OwnerUploadReceipt(status, attempted, test_mode)


def main() -> None:
    try:
        receipt = run_owner_probe().public_receipt()
    except Exception:
        receipt = OwnerUploadReceipt(
            "STOP_NOT_AUTHORIZED_OR_ALREADY_ATTEMPTED", False, False
        ).public_receipt()
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
