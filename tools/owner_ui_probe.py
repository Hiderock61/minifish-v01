"""Temporary private owner UI runner with allowlisted navigation diagnostics."""
import os
from pathlib import Path
import sys
from threading import Lock

ROOT = Path("/workspaces/minifish-v01")
FACTS = {"navigation": "NOT_OBSERVED", "http_code": 0,
         "url_allowed": False, "saved_state_loaded": False}
LOCK = Lock()


def install(owner):
    original_browser = owner.PlaywrightBrowser
    original_status = owner.handoff.status

    class ProbeBrowser(original_browser):
        def __enter__(self):
            super().__enter__()
            # Presence only. Never read or export storage state or cookies.
            with LOCK:
                FACTS["saved_state_loaded"] = bool(
                    self.session_vault and self.session_vault.path.exists())
            original_goto = self.page.goto

            def goto(*args, **kwargs):
                try:
                    response = original_goto(*args, **kwargs)
                    with LOCK:
                        FACTS.update(navigation="RESPONSE",
                                     http_code=response.status if response else 0,
                                     url_allowed=owner._approved_url(self.current_url))
                    return response
                except Exception:
                    with LOCK:
                        FACTS["navigation"] = "NAVIGATION_EXCEPTION"
                    raise

            self.page.goto = goto
            return self

    def status():
        result = original_status()
        with LOCK:
            result["navigation_probe"] = dict(FACTS)
        return result

    owner.PlaywrightBrowser = ProbeBrowser
    owner.handoff.status = status


def main():
    if os.getenv("CODESPACE_NAME") != "accursed-apparition-6q7jwqq5965h4rpq":
        raise SystemExit("HOLD_WRONG_CODESPACE")
    sys.path.insert(0, str(ROOT))
    import minifish.crowdworks_handoff as owner
    import g1b_mock_app
    import uvicorn
    install(owner)
    uvicorn.run(g1b_mock_app.app, host="127.0.0.1", port=8002,
                access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
