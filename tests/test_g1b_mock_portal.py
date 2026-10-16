"""Mock-only G1b private screen API regression + headed Chromium round trip."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
from cryptography.fernet import Fernet

import g1b_mock_app
from minifish.session_vault import EncryptedSessionVault


BASE = "http://127.0.0.1:8002"
HEADERS = {"Origin": BASE, "X-MiniFish-Mock-Action": "G1B"}


def request(path, *, method="GET", headers=None):
    req = urllib.request.Request(BASE + path, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=4) as response:
        return json.loads(response.read())


def wait_for(states, *, timeout=16):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = request("/g1b/status")
        if data["status"] in states and (data["status"] in ("WAITING_USER", "MOCK_CLICKED") or not data["busy"]):
            return data
        time.sleep(0.12)
    raise AssertionError("G1B_STATUS_TIMEOUT expected=" + str(states))


def test_gate_rejects_real_domains_and_unrelated_ports():
    class FakeRoute:
        def __init__(self, url):
            self.request = type("R", (), {"url": url})()
            self.result = ""
        def continue_(self):
            self.result = "ALLOWED"
        def abort(self):
            self.result = "BLOCKED"
    for url in (
        "https://www.lancers.jp/",
        "https://coconala.com/",
        "https://example.com/",
        "http://127.0.0.1:8000/",
        "file:///etc/passwd",
        "http://127.0.0.1:8002@evil.example/",
    ):
        route = FakeRoute(url)
        g1b_mock_app.local_only_request(route)
        assert route.result == "BLOCKED", url
    route = FakeRoute(BASE + "/mock/private")
    g1b_mock_app.local_only_request(route)
    assert route.result == "ALLOWED"


def test_private_codespaces_html_contract():
    assert "G1b 模擬ログイン" in g1b_mock_app.HTML
    assert "-6080.app.github.dev" in g1b_mock_app.HTML
    assert "X-MiniFish-Mock-Action" in g1b_mock_app.HTML
    assert "mockClick" in g1b_mock_app.HTML


@pytest.mark.skipif(os.getenv("MINIFISH_G1B_E2E") != "1",
                    reason="requires local Xvfb headed Chromium")
def test_private_mock_controller_save_relaunch_and_revoke(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = dict(os.environ, HOME=str(home), PYTHONPATH=str(Path.cwd()))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "g1b_mock_app:app",
         "--host", "127.0.0.1", "--port", "8002", "--no-access-log", "--log-level", "warning"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                assert request("/g1b/status")["status"] == "IDLE"
                break
            except Exception:
                time.sleep(.15)
        else:
            raise AssertionError("mock server did not start")

        with pytest.raises(urllib.error.HTTPError) as e:
            request("/g1b/start", method="POST")
        assert e.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as e:
            request("/g1b/start", method="POST",
                    headers={"Origin": "https://attacker.example",
                             "X-MiniFish-Mock-Action": "G1B"})
        assert e.value.code == 403

        request("/g1b/start", method="POST", headers=HEADERS)
        assert wait_for({"WAITING_USER", "BLOCKED"})["status"] == "WAITING_USER"
        with pytest.raises(urllib.error.HTTPError) as e:
            request("/g1b/start", method="POST", headers=HEADERS)
        assert e.value.code == 409
        request("/g1b/mock-click", method="POST", headers=HEADERS)
        assert wait_for({"MOCK_CLICKED", "BLOCKED"})["status"] == "MOCK_CLICKED"
        request("/g1b/save", method="POST", headers=HEADERS)
        assert wait_for({"SAVED", "BLOCKED"})["status"] == "SAVED"

        root = home / ".local/share/minifish/g1b-mock-only"
        ciphertext = (root / "mock_only.vault").read_bytes()
        assert b"NOT_A_REAL_ACCOUNT" not in ciphertext
        assert b"g1b_dummy" not in ciphertext
        assert (root / "mock_only.key").read_bytes()
        assert (root / "mock_only.vault").stat().st_mode & 0o777 == 0o600

        request("/g1b/verify", method="POST", headers=HEADERS)
        assert wait_for({"RESTORED_PASS", "BLOCKED"})["status"] == "RESTORED_PASS"

        # Session revoke must prevent restored login, including when
        # the encryption key still exists in private storage.
        (root / "mock_only.vault").unlink()
        request("/g1b/verify", method="POST", headers=HEADERS)
        assert wait_for({"BLOCKED"})["note"] == "NO_MOCK_SESSION"
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
