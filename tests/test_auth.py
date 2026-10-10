import json
from pathlib import Path

import pytest

from minifish.auth import SiteAuth, check_login, load_site, state_path, public_url


SITE = {
    "site_id": "mock_site",
    "base_url": "http://localhost:8765",
    "check_url": "http://localhost:8765/account",
    "success_selector": "#signed-in",
    "login_path_markers": ["/login", "/signin"],
}


def test_load_and_private_profile_paths(tmp_path):
    config = tmp_path / "sites.json"
    config.write_text(json.dumps({"sites": [SITE]}), encoding="utf-8")
    site = load_site("mock_site", config)
    assert site.site_id == "mock_site"
    assert state_path("mock_site", tmp_path) == tmp_path / "mock_site" / "storage.json"


def test_reject_traversal_and_other_site():
    with pytest.raises(ValueError):
        state_path("../escape")
    site = SiteAuth.from_dict(SITE)
    with pytest.raises(ValueError):
        site.validate_target("https://other.test/account")
    with pytest.raises(ValueError):
        SiteAuth.from_dict({**SITE, "check_url": "http://localhost:8888/account"})
    with pytest.raises(ValueError):
        SiteAuth.from_dict({**SITE, "base_url": "http://example.com"})


class FakeLocator:
    def __init__(self, works):
        self.works = works
    def wait_for(self, **kwargs):
        if not self.works:
            raise TimeoutError("not logged in")


class FakePage:
    def __init__(self, url, works):
        self.url = url
        self.works = works
    def locator(self, selector):
        assert selector == "#signed-in"
        return FakeLocator(self.works)


class FakeBrowser:
    def __init__(self, url, works):
        self.page = FakePage(url, works)
    def goto(self, url):
        self.page.url = url


def test_auth_requires_visible_proof():
    site = SiteAuth.from_dict(SITE)
    assert check_login(FakeBrowser(SITE["check_url"], True), site)
    assert not check_login(FakeBrowser(SITE["check_url"], False), site)
    assert not check_login(FakeBrowser("http://localhost:8765/login", True), site, navigate=False)
    assert not check_login(FakeBrowser("https://not-ours.test/account", True), site, navigate=False)


def test_public_url_redacts_query():
    assert public_url("https://example.com/a?token=secret#auth") == "https://example.com/a"
