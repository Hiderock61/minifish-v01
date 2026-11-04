import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "url_check", Path(__file__).resolve().parents[1] / "tools/crowdworks_url_accept.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
URL = "https://crowdworks.jp/login"


class UrlAcceptanceTests(unittest.TestCase):
    def test_success_requires_url_and_http(self):
        self.assertEqual(m.url_code(URL, URL, 200), "CROWDWORKS_LOGIN_URL_HTTP_PASS")

    def test_credentials_queries_fragments_are_rejected(self):
        for url in ("https://u:p@crowdworks.jp/login", URL + "?token=private",
                    URL + "#private", "https://crowdworks.jp:443/login"):
            self.assertFalse(m.approved_login(url))

    def test_wrong_host_scheme_and_path_are_rejected(self):
        for url in ("https://crowdworks.jp.evil.test/login", "http://crowdworks.jp/login",
                    "https://crowdworks.jp/", "https://crowdworks.jp:bad/login"):
            self.assertFalse(m.approved_login(url))

    def test_blocked_http_is_not_a_pass(self):
        for status in (None, 302, 401, 403, 429, 500):
            self.assertEqual(m.url_code(URL, URL, status), "HOLD_LOGIN_HTTP_NOT_SUCCESS")

    def test_response_and_current_url_must_both_match(self):
        self.assertEqual(m.url_code(URL, "https://example.org/login", 200),
                         "HOLD_LOGIN_URL_NOT_EXACT")


if __name__ == "__main__":
    unittest.main()
