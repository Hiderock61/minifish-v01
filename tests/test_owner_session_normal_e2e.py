"""Normal-package owner round trip against a synthetic localhost site only."""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
import time
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import g1b_mock_app
from minifish import crowdworks_handoff as owner
from minifish.browser import PlaywrightBrowser
from minifish import owner_runtime


def wait_state(manager, expected, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.status()
        if state["status"] == expected:
            return state
        if state["status"].startswith(("BLOCKED_", "STOPPED_")):
            raise AssertionError(state["status"] + "/" + state["stop_reason"])
        time.sleep(0.02)
    raise AssertionError("SYNTHETIC_OWNER_STATE_TIMEOUT")


@pytest.mark.skipif(
    os.getenv("MINIFISH_OWNER_SESSION_E2E") != "1",
    reason="requires the CI-installed Chromium browser",
)
def test_normal_owner_route_pump_save_and_restore(monkeypatch, tmp_path):
    repository = Path(__file__).resolve().parents[1]
    assert Path(owner.__file__).resolve() == repository / "minifish/crowdworks_handoff.py"
    assert owner_runtime._SCRIPT == repository / "start_g1b_mock.sh"
    authenticated_page = Event()
    visits = {"login": 0, "authenticated": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/login":
                visits["login"] += 1
                self.send_response(200)
                self.end_headers()
                # Synthetic user navigation starts after goto has returned.
                self.wfile.write(b"<script>setTimeout(()=>location.href='/auth',400)</script>")
            elif self.path == "/auth":
                self.send_response(303)
                self.send_header("Set-Cookie", "synthetic_owner=yes; HttpOnly; SameSite=Lax")
                self.send_header("Location", "/private")
                self.end_headers()
            elif self.path == "/private":
                valid = "synthetic_owner=yes" in self.headers.get("Cookie", "")
                self.send_response(200 if valid else 401)
                self.end_headers()
                if valid:
                    visits["authenticated"] += 1
                    authenticated_page.set()
                self.wfile.write(b"synthetic localhost page")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    origin = "http://127.0.0.1:" + str(server.server_port)
    monkeypatch.setenv("CODESPACE_NAME", "synthetic-normal-owner")
    monkeypatch.setattr(owner, "LOGIN_URL", origin + "/login")
    monkeypatch.setattr(owner, "HOME_URL", origin + "/private")
    monkeypatch.setattr(owner, "ROOT", tmp_path / "private-state")
    monkeypatch.setattr(owner, "_approved_url", lambda url: (
        urlsplit(url).scheme == "http" and urlsplit(url).netloc == urlsplit(origin).netloc
    ))
    # Headless is a test-only launch option. The production handoff, route,
    # wait loop, session vault and HTTP controls are imported normally.
    def browser_factory(**kwargs):
        kwargs["headless"] = True
        return PlaywrightBrowser(**kwargs)

    monkeypatch.setattr(owner, "PlaywrightBrowser", browser_factory)
    manager = owner.OwnerLoginHandoff()
    monkeypatch.setattr(g1b_mock_app, "real_handoff", manager)
    client = TestClient(g1b_mock_app.app)
    nonce = client.get("/g1/owner/status").json()["action_nonce"]
    saves = []
    from minifish.session_vault import EncryptedSessionVault
    original_save = EncryptedSessionVault.save

    def record_save(vault, state):
        saves.append(1)
        return original_save(vault, state)

    monkeypatch.setattr(EncryptedSessionVault, "save", record_save)
    try:
        assert client.post("/g1/owner/open", json={"nonce": nonce}).status_code == 200
        wait_state(manager, "WAITING_FOR_HUMAN")
        assert authenticated_page.wait(15), "ROUTED_MANUAL_NAVIGATION_DID_NOT_COMPLETE"
        assert client.post("/g1/owner/finish", json={"nonce": nonce}).status_code == 200
        wait_state(manager, "SESSION_SAVED_LOGIN_UNVERIFIED")
        assert client.post("/g1/owner/finish", json={"nonce": nonce}).status_code == 200
        assert len(saves) == 1
        vault = owner._secret_vault()
        ciphertext = vault.path.read_bytes()
        assert b"synthetic_owner" not in ciphertext
        assert vault.load() is not None

        authenticated_page.clear()
        logins_before = visits["login"]
        assert client.post("/g1/owner/reopen", json={"nonce": nonce}).status_code == 200
        state = wait_state(manager, "SESSION_REOPENED_LOGIN_NOT_VERIFIED")
        assert state["busy"]
        assert authenticated_page.is_set()
        assert visits["login"] == logins_before
        assert len(saves) == 1
        assert client.post("/g1/owner/stop", json={"nonce": nonce}).status_code == 200
        deadline = time.monotonic() + 10
        while manager.status()["busy"] and time.monotonic() < deadline:
            time.sleep(0.02)
        assert manager.status()["stop_reason"] == "OWNER_CANCELLED"
        assert vault.path.read_bytes() == ciphertext
    finally:
        if manager.status()["busy"]:
            manager.cancel()
            manager._worker.join(timeout=10)
        server.shutdown()
