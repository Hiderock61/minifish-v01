"""Browser-level owner-probe verification, no real CrowdWorks navigation/login."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

BASE = "http://127.0.0.1:8002"


@pytest.mark.skipif(
    os.getenv("MINIFISH_OWNER_BROWSER_E2E") != "1",
    reason="uses installed Chromium in private GUI acceptance workflow",
)
def test_real_chromium_probes_post_before_enabling_login(tmp_path):
    from playwright.sync_api import sync_playwright
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = dict(
        os.environ,
        HOME=str(home),
        CODESPACE_NAME="mini-test-codespace",
        PYTHONPATH=str(Path.cwd()),
    )
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "g1b_mock_app:app",
            "--host", "127.0.0.1", "--port", "8002",
            "--no-access-log", "--log-level", "warning",
        ],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(80):
            try:
                with urlopen(BASE + "/login-ready", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.15)
        else:
            raise AssertionError("OWNER_TEST_SERVER_NOT_READY")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                requests = []
                page.on("response", lambda response: requests.append(
                    (response.request.method, response.url, response.status)
                ))
                page.goto(BASE + "/login-ready")
                page.locator("#actionResult").get_by_text(
                    "自動通信検査OK", exact=False
                ).wait_for(timeout=15000)
                assert page.locator("#open").is_enabled()
                assert any(
                    method == "POST" and "/g1/owner/probe" in url and status == 200
                    for method, url, status in requests
                )
                assert not any(
                    method == "POST" and "/g1/owner/open" in url
                    for method, url, status in requests
                )
                # Emulate a Codespaces gateway that rewrites Origin while
                # retaining a browser-originated same-origin POST and nonce.
                forwarded = browser.new_page()
                forwarded.route(
                    "**/g1/owner/probe",
                    lambda route: route.continue_(headers={
                        **route.request.headers,
                        "origin": "https://github-port-relay.invalid",
                    }),
                )
                forwarded.goto(BASE + "/login-ready")
                forwarded.locator("#actionResult").get_by_text(
                    "自動通信検査OK", exact=False
                ).wait_for(timeout=15000)
                assert forwarded.locator("#open").is_enabled()
                # Fake an upstream 403. The page must show this reliably
                # without an owner button press or any website login.
                blocked = browser.new_page()
                blocked.route(
                    "**/g1/owner/probe",
                    lambda route: route.fulfill(
                        status=403,
                        content_type="application/json",
                        body='{"detail":"G1B_CROSS_SITE_REJECTED"}',
                    ),
                )
                blocked.goto(BASE + "/login-ready")
                blocked.locator("#actionResult").get_by_text(
                    "G1B_CROSS_SITE_REJECTED", exact=False
                ).wait_for(timeout=15000)
                assert blocked.locator("#open").is_disabled()
                assert blocked.locator("#finish").is_disabled()
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
