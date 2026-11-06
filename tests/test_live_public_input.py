"""Public Python docs input check: strict destination, genuine title, no submit."""
from urllib.parse import urlsplit

import pytest

from minifish import live_public_input as live


class FakeRoute:
    def __init__(self, url, method="GET"):
        self.request = type("Request", (), {"url": url, "method": method})()
        self.decision = None

    def continue_(self):
        self.decision = "CONTINUE"

    def abort(self):
        self.decision = "ABORT"


class FakeElement:
    def __init__(self, browser):
        self.browser = browser
        self.value = ""
        self.fill_count = 0
        self.submit_count = 0

    def is_visible(self):
        return self.browser.visible

    def is_enabled(self):
        return self.browser.enabled

    def fill(self, value, timeout):
        assert timeout <= 5000
        self.fill_count += 1
        self.value = value
        if self.browser.fill_mismatch:
            self.value = "different value"
        if self.browser.unexpected_navigation:
            self.browser.current_url = "https://docs.python.org/3/search.html?q=forbidden"

    def input_value(self):
        return self.value

    def press(self, *args, **kwargs):
        pytest.fail("must never press Enter or submit")

    def click(self, *args, **kwargs):
        pytest.fail("must never click submit")


class FakePage:
    def __init__(self, browser):
        self.browser = browser
        self.element = FakeElement(browser)
        self.goto_calls = []

    def goto(self, url, *, wait_until, timeout):
        assert wait_until == "domcontentloaded"
        assert timeout <= 20000
        self.goto_calls.append(url)
        route = FakeRoute(url)
        self.browser.route_handler(route)
        self.browser.route_decisions.append(route)
        assert route.decision in ("CONTINUE", "ABORT")
        self.browser.current_url = (
            self.browser.home_final if len(self.goto_calls) == 1
            else self.browser.search_final
        )
        if route.decision == "ABORT":
            return None
        status = (self.browser.home_status if len(self.goto_calls) == 1
                  else self.browser.search_status)
        return type("Response", (), {"status": status})()

    def title(self):
        return self.browser.title

    def locator(self, selector):
        if selector == "input[name='q']" and self.browser.has_search_input:
            return type("Matches", (), {
                "count": lambda _: 1,
                "nth": lambda _, idx: self.element,
            })()
        return type("Empty", (), {"count": lambda _: 0})()


class FakeContext:
    def __init__(self, browser):
        self.browser = browser

    def route(self, pattern, callback):
        assert pattern == "**/*"
        self.browser.route_handler = callback


class FakeBrowser:
    def __init__(self, *, title="Python 3.15.2 documentation",
                 home_status=200, search_status=200,
                 home_final=live.PUBLIC_URL, search_final=live.SEARCH_URL,
                 has_search_input=True, visible=True, enabled=True,
                 fill_mismatch=False, unexpected_navigation=False):
        self.title = title
        self.home_status = home_status
        self.search_status = search_status
        self.home_final = home_final
        self.search_final = search_final
        self.has_search_input = has_search_input
        self.visible = visible
        self.enabled = enabled
        self.fill_mismatch = fill_mismatch
        self.unexpected_navigation = unexpected_navigation
        self.current_url = ""
        self.route_handler = None
        self.route_decisions = []
        self.context = FakeContext(self)
        self.page = FakePage(self)
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.entered = False


def run(monkeypatch, **settings):
    browser = FakeBrowser(**settings)
    def factory(**kwargs):
        assert kwargs == {
            "headless": True, "profile_path": None, "capture_dir": None,
        }
        return browser
    monkeypatch.setattr(live, "PlaywrightBrowser", factory)
    return live.real_public_typing(), browser


@pytest.mark.parametrize("title", (
    "Python 3.15.2 documentation",
    "Python 3.14.7 Documentation",
    "Python 3.15 documentation",
))
def test_real_official_python_titles_and_readback_pass(monkeypatch, title):
    result, browser = run(monkeypatch, title=title)
    assert result["status"] == "PASS"
    assert result["reason"] == "REAL_PUBLIC_INPUT_NOT_SUBMITTED"
    assert result["public_http_status"] == 200
    assert result["search_http_status"] == 200
    assert result["public_final_url"] == live.PUBLIC_URL
    assert result["public_title"] == title
    assert result["observed_public_page"] is True
    assert result["typing_verified"] is True
    assert result["submitted"] is False
    assert result["external_writes"] == 0
    assert result["login_attempts"] == 0
    assert result["http_mutations_allowed"] == 0
    assert result["request_with_query"] is False
    assert browser.page.goto_calls == [live.PUBLIC_URL, live.SEARCH_URL]
    assert browser.page.element.fill_count == 1
    assert browser.page.element.value == live.TEXT


@pytest.mark.parametrize("title", (
    "Documentation",
    "Python Documentation", 
    "Access denied - Python documentation",
    "Just a moment... documentation",
    "Search — Python 3.15.2 documentation",
    "Python 3.15.2 documentation - Fake",
    "Python 2.7 documentation",
))
def test_title_rejects_unverified_or_wrong_public_page(monkeypatch, title):
    result, browser = run(monkeypatch, title=title)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "PUBLIC_PAGE_UNEXPECTED"
    assert browser.page.goto_calls == [live.PUBLIC_URL]
    assert browser.page.element.fill_count == 0
    assert result["external_writes"] == 0


@pytest.mark.parametrize("home_status", (301, 403, 429, 500))
def test_public_home_requires_http_200(monkeypatch, home_status):
    result, browser = run(monkeypatch, home_status=home_status)
    assert result["reason"] == "PUBLIC_READ_FAILED"
    assert result["public_http_status"] == home_status
    assert browser.page.element.fill_count == 0


@pytest.mark.parametrize("search_status", (301, 403, 429, 500))
def test_search_requires_http_200(monkeypatch, search_status):
    result, browser = run(monkeypatch, search_status=search_status)
    assert result["reason"] == "SEARCH_PAGE_UNAVAILABLE"
    assert result["search_http_status"] == search_status
    assert browser.page.element.fill_count == 0


def test_unapproved_home_redirect_is_rejected(monkeypatch):
    result, browser = run(monkeypatch, home_final="https://evil.example/3/")
    assert result["reason"] == "PUBLIC_READ_FAILED"
    assert "public_final_url" not in result
    assert browser.page.element.fill_count == 0


@pytest.mark.parametrize("new_url", (
    "https://docs.python.org/3.15/search.html",
    "https://docs.python.org/3/search.html?q=sent",
    "https://docs.python.org/3/search.html#anchor",
    "https://docs.python.org.evil.example/3/search.html",
))
def test_search_redirect_cannot_be_silently_accepted(monkeypatch, new_url):
    result, browser = run(monkeypatch, search_final=new_url)
    assert result["reason"] == "SEARCH_PAGE_UNAVAILABLE"
    assert result["submitted"] is False
    assert browser.page.element.fill_count == 0


@pytest.mark.parametrize("settings", (
    {"has_search_input": False},
    {"visible": False},
    {"enabled": False},
))
def test_missing_hidden_or_disabled_input_rejected(monkeypatch, settings):
    result, browser = run(monkeypatch, **settings)
    assert result["reason"] == "SEARCH_INPUT_NOT_VISIBLE"
    assert browser.page.element.fill_count == 0


def test_fill_readback_mismatch_fails_closed(monkeypatch):
    result, browser = run(monkeypatch, fill_mismatch=True)
    assert result["reason"] == "INPUT_READBACK_MISMATCH"
    assert result["typing_verified"] is False
    assert browser.page.element.fill_count == 1
    assert result["submitted"] is False


def test_unexpected_navigation_after_fill_rejected(monkeypatch):
    result, browser = run(monkeypatch, unexpected_navigation=True)
    assert result["reason"] == "UNEXPECTED_NAVIGATION"
    assert browser.page.element.fill_count == 1
    assert result["submitted"] is False


@pytest.mark.parametrize("method,url", (
    ("POST", "https://docs.python.org/3/"),
    ("PUT", "https://docs.python.org/3/"),
    ("GET", "https://docs.python.org/3/search.html?q=sent"),
    ("GET", "https://docs.python.org/3/search.html#fragment"),
    ("GET", "https://docs.python.org.evil.example/3/"),
    ("GET", "https://evil.example/3/"),
    ("GET", "http://docs.python.org/3/"),
    ("GET", "https://docs.python.org:8443/3/"),
    ("GET", "https://docs.python.org/2/"),
))
def test_external_write_and_nonallowlisted_destination_blocked(monkeypatch, method, url):
    _, browser = run(monkeypatch)
    route = FakeRoute(url, method)
    browser.route_handler(route)
    assert route.decision == "ABORT"


def test_resource_count_limit_blocks_251st(monkeypatch):
    _, browser = run(monkeypatch)
    route = None
    for _ in range(live.MAX_RESOURCE_COUNT + 1):
        route = FakeRoute(live.SEARCH_URL)
        browser.route_handler(route)
    assert route.decision == "ABORT"
