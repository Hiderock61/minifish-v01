"""G1 end-to-end: a local-only pretend site, two new Chromium sessions.

No real websites, user accounts, credentials, API, or external writes.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from cryptography.fernet import Fernet
import os
from pathlib import Path

import pytest

from minifish.browser import PlaywrightBrowser
from minifish.session_vault import EncryptedSessionVault


class MockSite(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return  # no cookie or request header logs

    def respond(self, status, body, headers=()):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/login":
            return self.respond(200, '<form method="post" action="/auth">'
                                '<button type="submit">Mock login</button></form>')
        if self.path == "/private":
            authorized = "g1_mock=TEST_ONLY" in self.headers.get("Cookie", "")
            return self.respond(200, "<h1>AUTHORIZED_TEST_ONLY</h1>" if authorized
                                else "<h1>LOGIN_REQUIRED</h1>")
        return self.respond(404, "<h1>NOT_FOUND</h1>")

    def do_POST(self):
        if self.path != "/auth":
            return self.respond(404, "<h1>NOT_FOUND</h1>")
        self.send_response(303)
        self.send_header("Set-Cookie", "g1_mock=TEST_ONLY; HttpOnly; SameSite=Lax; Path=/")
        self.send_header("Location", "/private")
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.mark.skipif(os.getenv("MINIFISH_G1_E2E") != "1",
                    reason="requires dedicated local Chromium runner")
def test_mock_login_survives_browser_recreation(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockSite)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{server.server_port}"
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    vault = EncryptedSessionVault(private / "mock.vault", Fernet.generate_key())
    try:
        with PlaywrightBrowser(session_vault=vault, capture_dir=None) as browser:
            browser.goto(url + "/login")
            browser.page.get_by_role("button", name="Mock login").click()
            browser.page.wait_for_url("**/private")
            assert "AUTHORIZED_TEST_ONLY" in browser.observe().text_excerpt

        assert vault.path.exists()
        ciphertext = vault.path.read_bytes()
        assert b"TEST_ONLY" not in ciphertext
        assert b"g1_mock" not in ciphertext

        # Completely new Playwright process; no prior in-memory context.
        with PlaywrightBrowser(session_vault=vault, capture_dir=None) as browser:
            browser.goto(url + "/private")
            assert "AUTHORIZED_TEST_ONLY" in browser.observe().text_excerpt

        # Without access to the vault the same private page is still locked.
        with PlaywrightBrowser(profile_path=None, capture_dir=None) as browser:
            browser.goto(url + "/private")
            assert "LOGIN_REQUIRED" in browser.observe().text_excerpt

        # A removed vault immediately revokes local reuse.
        vault.path.unlink()
        with PlaywrightBrowser(session_vault=vault, capture_dir=None) as browser:
            browser.goto(url + "/private")
            assert "LOGIN_REQUIRED" in browser.observe().text_excerpt
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=3)
