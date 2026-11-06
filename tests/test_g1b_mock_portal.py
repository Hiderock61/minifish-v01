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
    assert "-6081.app.github.dev" in g1b_mock_app.HTML
    assert "showPass" in g1b_mock_app.HTML
    assert "X-MiniFish-Mock-Action" in g1b_mock_app.HTML
    assert "mockClick" in g1b_mock_app.HTML


@pytest.mark.skipif(os.getenv("MINIFISH_G1B_E2E") != "1",
                    reason="requires local Xvfb headed Chromium")
def test_private_mock_controller_save_relaunch_and_revoke(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = dict(os.environ, HOME=str(home), PYTHONPATH=str(Path.cwd()),
               PLAYWRIGHT_BROWSERS_PATH=str(Path.home() / ".cache/ms-playwright"))
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
        first_state = wait_for({"WAITING_USER", "BLOCKED"})
        assert first_state["status"] == "WAITING_USER", first_state
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


def test_private_port_and_no_embedded_password():
    cfg = json.loads(Path(".devcontainer/devcontainer.json").read_text(encoding="utf-8"))
    assert 6081 in cfg["forwardPorts"]
    assert 6080 not in cfg["forwardPorts"]
    assert cfg["portsAttributes"]["6081"]["visibility"] == "private"
    assert cfg["portsAttributes"]["8002"]["visibility"] == "private"
    for port in ("6080", "5901", "5911"):
        assert cfg["portsAttributes"][port]["onAutoForward"] == "ignore"
    assert "password" not in cfg["features"]["ghcr.io/devcontainers/features/desktop-lite:1"]
    script = Path("start_g1b_mock.sh").read_text(encoding="utf-8")
    assert 'secrets.choice(alphabet)' in script
    assert 'tigervncserver :11' in script
    assert '--listen 6081' in script
    assert '-localhost -SecurityTypes VncAuth' in script
    assert 'CODESPACE_NAME' in script
    assert "G1B_MOCK_ONLY" not in script
    result = subprocess.run(["bash", "-n", "start_g1b_mock.sh"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    result = subprocess.run(["env", "-u", "CODESPACE_NAME",
                             "-u", "MINIFISH_G1B_LOCAL_TEST", "bash", "start_g1b_mock.sh"],
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "G1B_BLOCKED_NOT_PRIVATE_CODESPACE" in result.stdout


def _fake_request(headers):
    from starlette.requests import Request
    scope = {
        "type": "http", "method": "POST", "scheme": "http",
        "server": ("127.0.0.1", 8002), "path": "/g1b/vnc-password",
        "root_path": "", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def test_vnc_password_only_revealed_on_private_authenticated_mock_control(monkeypatch, tmp_path):
    from fastapi import HTTPException
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    secret = private / "vnc-password.txt"
    secret.write_text("X3y4z5Q7", encoding="ascii")
    secret.chmod(0o600)
    monkeypatch.setenv("CODESPACE_NAME", "test-mock-codespace")
    monkeypatch.setattr(g1b_mock_app, "private_root", lambda: private)

    with pytest.raises(HTTPException) as exc:
        g1b_mock_app.vnc_password(_fake_request({"host": "127.0.0.1:8002"}))
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        g1b_mock_app.vnc_password(_fake_request({
            "host": "127.0.0.1:8002",
            "origin": "https://attacker.example",
            "x-minifish-mock-action": "G1B",
        }))
    assert exc.value.status_code == 403

    valid = _fake_request({
        "host": "127.0.0.1:8002",
        "origin": "http://127.0.0.1:8002",
        "x-minifish-mock-action": "G1B",
    })
    response = g1b_mock_app.vnc_password(valid)
    assert response.headers["Cache-Control"] == "no-store"
    assert json.loads(response.body)["password"] == "X3y4z5Q7"
    assert "X3y4z5Q7" not in g1b_mock_app.HTML
    assert "X3y4z5Q7" not in str(g1b_mock_app.status())

    secret.chmod(0o644)
    with pytest.raises(HTTPException) as exc:
        g1b_mock_app.vnc_password(valid)
    assert exc.value.status_code == 503
