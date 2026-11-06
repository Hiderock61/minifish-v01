"""No-auth prelogin gate: fixed sites, no passwords, no submission."""
from __future__ import annotations
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from minifish import prelogin


def test_four_exact_official_login_urls_and_human_stop():
    assert list(prelogin.SITES) == ["lancers", "coconala", "crowdworks", "note"]
    assert [prelogin.SITES[k].login_url for k in prelogin.SITES] == [
        "https://www.lancers.jp/user/login",
        "https://coconala.com/login",
        "https://crowdworks.jp/login",
        "https://note.com/login",
    ]
    for key in prelogin.SITES:
        site = prelogin.safe_login_site(key)
        assert site.key == key
        with pytest.raises(FrozenInstanceError):
            site.host = "evil.example"
    summary = prelogin.summary()
    assert summary["site_count"] == 4
    assert summary["login_pending"]
    assert summary["next_human_action"] == "LOGIN_WHEN_USER_CHOOSES"
    assert summary["openai_api_calls"] == 0
    assert summary["external_writes"] == 0


@pytest.mark.parametrize("bad", [
    "", "lancer", "wordpress", None, False, 1,
    "https://note.com/login", "note?redirect=https://evil.example"
])
def test_no_unregistered_site_can_start(bad):
    with pytest.raises(ValueError, match="G1_PRELOGIN_SITE_NOT_APPROVED"):
        prelogin.safe_login_site(bad)


class FakeResponse:
    status = 200


class FakeLocator:
    def __init__(self, count):
        self._count = count
    def count(self):
        return self._count


class FakePage:
    def __init__(self, url):
        self.url = url
        self.seen = []
        self.main_frame = object()
    def goto(self, url, **kw):
        self.seen.append(("goto", url, kw))
        self.url = url
        return FakeResponse()
    def wait_for_timeout(self, ms):
        self.seen.append(("wait", ms))
    def locator(self, selector):
        self.seen.append(("locator", selector))
        if selector == 'input[type="password"]':
            return FakeLocator(1)
        return FakeLocator(1)


class FakeContext:
    def __init__(self):
        self.routes = []
    def route(self, pattern, cb):
        self.routes.append((pattern, cb))


class FakeBrowser:
    created = []
    def __init__(self, **kwargs):
        self.created.append(kwargs)
        self.context = FakeContext()
        self.page = FakePage("about:blank")
    def __enter__(self): return self
    def __exit__(self, *args): return False


def test_each_site_stops_before_login_and_never_types(monkeypatch):
    FakeBrowser.created.clear()
    monkeypatch.setattr(prelogin, "PlaywrightBrowser", FakeBrowser)
    for key in prelogin.SITES:
        res = prelogin.observe_login_only(key)
        assert res["site"] == key
        assert res["status"] == "LOGIN_FIELDS_VISIBLE"
        assert res["stop"] == "HUMAN_LOGIN_REQUIRED"
        assert res["auth_attempts"] == res["form_fills"] == res["form_submits"] == 0
        assert res["external_writes"] == res["openai_api_calls"] == 0
        assert "password" not in str(res)
    assert len(FakeBrowser.created) == 4
    assert all(x["profile_path"] is None and x["capture_dir"] is None
               for x in FakeBrowser.created)


def test_failure_does_not_leak_exception_or_claim_success(monkeypatch):
    class CannotLaunch:
        def __init__(self, **kwargs): raise ValueError("secret: abc123")
    monkeypatch.setattr(prelogin, "PlaywrightBrowser", CannotLaunch)
    report = prelogin.observe_login_only("note")
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "G1_READ_ONLY_BROWSER_UNAVAILABLE"
    assert "abc123" not in str(report)
