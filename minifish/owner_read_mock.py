"""Isolated owner-read acceptance fixture: synthetic HTTP and synthetic cookies ONLY.

No real CrowdWorks URL, no owner vault/key, no AI/API request, no GitHub
artifact, and no content returned by the production Issue bridge.
The test caller is the only intended user of this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from .browser import PlaywrightBrowser
from .session_vault import EncryptedSessionVault


_FAKE_COOKIE_VALUE = "SYNTHETIC_ONLY_NOT_A_REAL_CREDENTIAL"
_FAKE_TITLES = ("架空案件A：CSVの空欄確認", "架空案件B：公開資料の整理")


@dataclass(frozen=True)
class MockReadProof:
    status: str
    titles: tuple[str, ...]
    vault_unchanged: bool
    get_requests: int
    reason: str

    def public_receipt(self) -> dict[str, object]:
        """This is the ONLY return value the Issue worker may receive."""
        return {
            "mode": "owner_read_mock",
            "status": self.status,
            "reason": self.reason,
            "title_count": len(self.titles) if self.status == "PASS" else 0,
            "vault_unchanged": self.vault_unchanged,
            "website_writes": 0,
            "paid_api_calls": 0,
            "real_site_calls": 0,
            "credential_values_included": False,
            "title_values_included": False,
        }


class _MockSite(BaseHTTPRequestHandler):
    get_requests = 0

    def log_message(self, *args):
        return  # Do not log the fake Cookie header or page content.

    def do_GET(self):
        type(self).get_requests += 1
        if self.path != "/private":
            return self._reply(404, "<h1>MOCK_NOT_FOUND</h1>")
        if "mock_owner=" + _FAKE_COOKIE_VALUE not in self.headers.get("Cookie", ""):
            return self._reply(401, "<h1>LOGIN_REQUIRED</h1>")
        titles = "".join(
            '<article data-minifish-mock-title="1">' + title + "</article>"
            for title in _FAKE_TITLES
        )
        # This fake secret is rendered in the body to catch accidental bulk export.
        return self._reply(
            200, "<main><h1>SYNTHETIC_ACCOUNT_ONLY</h1>" + titles
            + "<p>PRIVATE_MOCK_SENTINEL_DO_NOT_PUBLISH</p></main>"
        )

    def do_POST(self):
        return self._reply(405, "<h1>READ_ONLY</h1>")

    def _reply(self, status: int, html: str):
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _allow_local_get(route, port: int):
    """Forbid any navigation, scripts or requests away from this mock server."""
    request = route.request
    parsed = urlsplit(request.url)
    if (request.method == "GET" and parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1" and parsed.port == port
            and parsed.username is None and parsed.password is None
            and parsed.path == "/private" and not parsed.query
            and not parsed.fragment):
        route.continue_()
    else:
        route.abort()


def run_mock_read(*, authenticated: bool = True) -> MockReadProof:
    """End-to-end mock: encrypted fake session -> fresh Chromium -> titles.

    The real owner Vault is never referenced. The test-only Vault is never
    rewritten by the read. Only a count, never titles/cookies, can cross
    into a public GitHub Issue receipt.
    """
    with TemporaryDirectory(prefix="minifish-owner-read-mock-") as folder:
        private = Path(folder)
        vault = EncryptedSessionVault(private / "fake-session.vault",
                                      Fernet.generate_key())
        if authenticated:
            vault.save({
                "cookies": [{
                    "name": "mock_owner",
                    "value": _FAKE_COOKIE_VALUE,
                    "domain": "127.0.0.1",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": True,
                    "secure": False,
                    "sameSite": "Lax",
                }],
                "origins": [],
            })
        initial_bytes = vault.path.read_bytes() if vault.path.exists() else None
        _MockSite.get_requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockSite)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        try:
            with PlaywrightBrowser(
                session_vault=vault, save_session_on_exit=False,
                profile_path=None, capture_dir=None,
            ) as browser:
                assert browser.context is not None and browser.page is not None
                browser.context.route("**/*",
                                      lambda route: _allow_local_get(route, port))
                url = f"http://127.0.0.1:{port}/private"
                navigation = browser.goto(url)
                authorized = (
                    navigation.get("http_status") == 200
                    and browser.current_url == url
                    and browser.page.locator("h1").inner_text() ==
                        "SYNTHETIC_ACCOUNT_ONLY"
                )
                titles = tuple(
                    t.strip()[:120] for t in
                    browser.page.locator("[data-minifish-mock-title]").all_inner_texts()
                    if t.strip()
                ) if authorized else ()
            after_bytes = vault.path.read_bytes() if vault.path.exists() else None
            unchanged = initial_bytes == after_bytes
            passed = authenticated and titles == _FAKE_TITLES and unchanged
            return MockReadProof(
                status="PASS" if passed else "BLOCKED",
                titles=titles if passed else (),
                vault_unchanged=unchanged,
                get_requests=_MockSite.get_requests,
                reason="SYNTHETIC_READ_CONFIRMED" if passed else
                       "SYNTHETIC_LOGIN_OR_READ_NOT_CONFIRMED",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
