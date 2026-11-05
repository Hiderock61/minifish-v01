import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import unittest

spec = importlib.util.spec_from_file_location("probe", Path(__file__).resolve().parents[1] / "tools/owner_ui_probe.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ProbeTests(unittest.TestCase):
    def owner(self, fail=False):
        class Browser:
            def __enter__(self):
                self.session_vault = None
                self.current_url = "https://crowdworks.jp/login?private=SECRET"
                def goto(*args, **kwargs):
                    if fail:
                        raise RuntimeError("SECRET")
                    return SimpleNamespace(status=200)
                self.page = SimpleNamespace(goto=goto)
                return self
        return SimpleNamespace(PlaywrightBrowser=Browser,
            handoff=SimpleNamespace(status=lambda: {"status":"WAITING_FOR_HUMAN"}),
            _approved_url=lambda url: True)

    def test_response_is_observed_without_url_or_body(self):
        owner = self.owner()
        m.install(owner)
        browser = owner.PlaywrightBrowser().__enter__()
        response = browser.page.goto("approved")
        self.assertEqual(response.status, 200)
        self.assertEqual(owner.handoff.status()["navigation_probe"]["http_code"], 200)
        self.assertNotIn("SECRET", json.dumps(owner.handoff.status()))

    def test_exception_text_does_not_escape_status(self):
        owner = self.owner(fail=True)
        m.install(owner)
        browser = owner.PlaywrightBrowser().__enter__()
        with self.assertRaises(RuntimeError):
            browser.page.goto("approved")
        self.assertEqual(owner.handoff.status()["navigation_probe"]["navigation"],
                         "NAVIGATION_EXCEPTION")
        self.assertNotIn("SECRET", json.dumps(owner.handoff.status()))

    def test_status_read_is_a_copy(self):
        owner = self.owner()
        m.install(owner)
        state = owner.handoff.status()
        state["navigation_probe"]["navigation"] = "PRIVATE"
        self.assertNotEqual(owner.handoff.status()["navigation_probe"]["navigation"], "PRIVATE")

if __name__ == "__main__":
    unittest.main()
