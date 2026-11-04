"""Inspect existing owner handoff navigation without credentials or saved state."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path("/workspaces/minifish-v01")


def approved_login(url):
    try:
        value = urlsplit(url)
        return (value.scheme == "https" and value.hostname == "crowdworks.jp"
                and value.port is None and value.username is None
                and value.password is None and not value.query and not value.fragment
                and value.path.rstrip("/") in ("/login", "/users/sign_in"))
    except (ValueError, TypeError):
        return False


def url_code(current, response_url, status):
    if not approved_login(current) or not approved_login(response_url):
        return "HOLD_LOGIN_URL_NOT_EXACT"
    if not isinstance(status, int) or not 200 <= status < 300:
        return "HOLD_LOGIN_HTTP_NOT_SUCCESS"
    return "CROWDWORKS_LOGIN_URL_HTTP_PASS"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    # Both helpers are SHA-checked before execution by the operator.
    gui = load_module("gui_check", Path(sys.argv[1]))
    gui.gate()
    sys.path.insert(0, str(ROOT))
    import minifish.crowdworks_handoff as owner
    result = {"url_verdict": "HOLD_NAVIGATION_NOT_OBSERVED",
              "window_verdict": "HOLD_WINDOW_NOT_OBSERVED",
              "private_share": "HOLD_SHARE_NOT_CHECKED",
              "login_performed": False, "session_saved": False}
    cancel = Event()

    class ObservedBrowser(owner.PlaywrightBrowser):
        def __enter__(self):
            super().__enter__()
            original = self.page.goto

            def navigate(*args, **kwargs):
                response = original(*args, **kwargs)
                result["url_verdict"] = url_code(
                    self.current_url, response.url if response else "",
                    response.status if response else None)
                return response

            self.page.goto = navigate
            return self

    class ObservedHandoff(owner.OwnerLoginHandoff):
        def _set(self, state):
            super()._set(state)
            if state != "WAITING_FOR_HUMAN":
                return
            try:
                # Observe THIS worker's status around the same window inspection.
                with patch.object(gui, "owner_status", lambda: self.status()["status"]):
                    verdict, fields = gui.inspect()
                result["window_verdict"] = verdict
                for key in ("chromium_class_seen", "chromium_pid_owner_verified",
                            "chromium_mapped_viewable", "chromium_visible_window_count",
                            "owner_status", "owner_state_stable"):
                    result[key] = fields[key]
                check = subprocess.run(
                    [sys.executable, "-B", sys.argv[2], "--connect"],
                    capture_output=True, text=True, timeout=75, check=False)
                # Raw helper stdout/stderr must never escape.
                if check.returncode == 0:
                    data = json.loads(check.stdout)
                    if data.get("verdict") == "NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE":
                        result["private_share"] = "NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE"
            except Exception:
                result["private_share"] = "HOLD_SHARE_INSPECTION"
            finally:
                cancel.set()

    # No existing vault or cookies are loaded. Cancel always exits via the
    # original _StopWithoutSaving path before the original save branch.
    with patch.object(owner, "PlaywrightBrowser", ObservedBrowser), patch.object(
            owner, "_secret_vault", return_value=None):
        handoff = ObservedHandoff()
        handoff._run(False, Event(), cancel)
    result["handoff_final"] = handoff.status()["status"]
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"verdict":"HOLD_URL_ACCEPTANCE_UNKNOWN"}', flush=True)
        sys.exit(2)
