"""Safety regression suite: exact URL allowlist, mode isolation, proof checks."""
import json

import pytest

from minifish.issue_contract import readonly_issue_payload
from minifish.public_sites import PUBLIC_SITES, observed_url_allowed, site_for_url
from minifish.command_tower import MiniFishCommandTower


@pytest.mark.parametrize("key", ["example", "python", "github"])
def test_registered_catalog_sites_have_exact_https_destinations(key):
    s = PUBLIC_SITES[key]
    assert site_for_url(s.url) is s
    assert observed_url_allowed(s, s.url)
    assert MiniFishCommandTower.preflight_public_readonly(
        "issue_123", "公開ページだけを観測", s.url
    ).state == "PASS"


@pytest.mark.parametrize("url", [
    "https://example.com.evil.invalid/",
    "https://example.com/?s=1",
    "https://docs.python.org/3/?token=secret",
    "https://docs.python.org/3/other",
    "http://docs.python.org/3/",
    "https://github.com/Hiderock61/minifish-v01/issues/5",
    "https://github.com/Hiderock61/minifish-v01.evil.invalid",
    "https://user:password@github.com/Hiderock61/minifish-v01",
    "https://127.0.0.1/",
    "http://169.254.169.254/",
    "file:///etc/passwd",
    "javascript:alert(1)",
])
def test_arbitrary_url_and_secret_bearing_urls_blocked(url):
    assert site_for_url(url) is None
    assert MiniFishCommandTower.preflight_public_readonly(
        "issue_123", "Read page", url
    ).state == "STOP"


def test_redirect_cannot_escape_registered_host_or_path():
    site = PUBLIC_SITES["github"]
    for url in (
        "https://github.com/Hiderock61/minifish-v01.evil",
        "https://github.com/other/repo",
        "https://github.com/Hiderock61/minifish-v01?key=secret",
        "http://github.com/Hiderock61/minifish-v01",
        "https://evil.invalid/Hiderock61/minifish-v01",
    ):
        assert not observed_url_allowed(site, url)
    assert observed_url_allowed(
        site, "https://github.com/Hiderock61/minifish-v01/issues"
    )


def _issue(body, title="[MINIFISH READ] valid"):
    return {"number": 27, "title": title, "body": body}


def test_only_read_only_issues_reach_existing_bridge():
    okay = _issue(json.dumps({
        "mode": "read_only", "url": "https://example.com/",
        "goal": "Example Domain公開ページを確認する"
    }))
    actual = readonly_issue_payload(okay)
    assert actual["number"] == 27
    assert json.loads(actual["body"])["mode"] == "read_only"


@pytest.mark.parametrize("body", [
    {"mode": "agent", "url": "https://example.com/", "goal": "anything"},
    {"mode": "demo", "url": "https://example.com/", "goal": "anything"},
    {"mode": "read_only", "url": "https://example.com/", "goal": "a", "allow_billable": True},
    {"mode": "read_only", "url": "https://example.com/"},
    ["not an object"],
])
def test_mode_escalation_and_injected_fields_never_dispatch(body):
    with pytest.raises(ValueError):
        readonly_issue_payload(_issue(json.dumps(body)))


def test_bad_json_and_wrong_title_blocked():
    with pytest.raises(ValueError):
        readonly_issue_payload(_issue("{"))
    with pytest.raises(ValueError):
        readonly_issue_payload(_issue('{"mode":"read_only"}', "Untrusted issue"))


def test_never_skip_control_gate_for_unapproved_site():
    d = MiniFishCommandTower.preflight_public_readonly(
        "issue_99", "Read", "https://docs.python.org/3/#fragment"
    )
    assert d.state == "STOP"
