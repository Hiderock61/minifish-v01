"""Local fake website: prove save -> browser exit -> restore -> revoke -> WAITING."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json

from minifish.auth import SiteAuth, check_login
from minifish.browser import PlaywrightBrowser
from minifish.runner import MiniFishRunner
from minifish.planner import ScriptedPlanner
from minifish.models import Action


class LoginHandler(BaseHTTPRequestHandler):
    revoked = False

    def do_GET(self):
        if self.path == "/perform_login":
            self.send_response(302)
            self.send_header("Set-Cookie", "mock_session=valid; HttpOnly; SameSite=Lax; Path=/")
            self.send_header("Location", "/account")
            self.end_headers()
        elif self.path == "/account":
            authorized = "mock_session=valid" in self.headers.get("Cookie", "") and not type(self).revoked
            if not authorized:
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><title>Private User Page</title><p id='signed-in'>private test info</p></html>")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><a href='/perform_login'>Click to sign in</a></html>")

    def log_message(self, *args):
        pass


def test_real_chromium_session_restore_and_auth_expiry(tmp_path):
    LoginHandler.revoked = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), LoginHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        site = SiteAuth.from_dict({
            "site_id": "mock_site", "base_url": url,
            "check_url": url + "/account", "success_selector": "#signed-in",
            "login_path_markers": ["/login"],
        })
        state_path = tmp_path / "storage.json"
        with PlaywrightBrowser(headless=True, profile_path=str(state_path), save_profile_on_close=False) as b:
            b.goto(url + "/login")
            b.page.get_by_text("Click to sign in").click()
            assert check_login(b, site)
            b.save_profile_on_close = True
        assert state_path.exists()
        assert state_path.stat().st_mode & 0o077 == 0

        with PlaywrightBrowser(headless=True, profile_path=str(state_path), save_profile_on_close=False) as b:
            assert check_login(b, site)

        run_log = tmp_path / "run.json"
        runner = MiniFishRunner(
            ScriptedPlanner([Action(type="done", result="account reached")]),
            auth_site=site, profile_path=str(state_path),
            log_path=str(run_log), capture_dir=str(tmp_path / "private-captures"),
        )
        result = runner.run(goal="Read my mock account", start_url=url + "/account")
        assert result.status == "COMPLETED"
        payload = run_log.read_text(encoding="utf-8")
        assert "private test info" not in payload
        assert not (tmp_path / "private-captures").exists()

        LoginHandler.revoked = True
        runner = MiniFishRunner(
            ScriptedPlanner([Action(type="done", result="should not run")]),
            auth_site=site, profile_path=str(state_path),
        )
        result = runner.run(goal="Read my mock account", start_url=url + "/account")
        assert result.status == "WAITING"
        assert "AUTH_REQUIRED" in result.final_result
        assert result.events == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
