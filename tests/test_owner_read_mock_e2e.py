"""Contract tests for a synthetic, LOCAL-ONLY owner-read connection.

GitHub Issue-shaped command -> existing bridge -> synthetic Chromium read ->
publicly safe receipt. Real owner session, real domain, external submission,
AI/API calls and production dispatch are NEVER used.
"""
import json
import os

import pytest

import bridge_worker
from minifish.owner_read_mock import run_mock_read

MOCK_E2E = os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") == "1"
EXACT_GOAL = "READ_SYNTHETIC_JOB_TITLES"


def fake_issue(*, goal=EXACT_GOAL, url=None):
    payload = {"mode": "owner_read_mock", "goal": goal}
    if url is not None:
        payload["url"] = url
    return {"number": 4092, "body": json.dumps(payload, ensure_ascii=False)}


def test_synthetic_command_is_disabled_in_normal_runtime(monkeypatch):
    monkeypatch.delenv("MINIFISH_G1_PRIVATE_MOCK_E2E", raising=False)
    with pytest.raises(ValueError, match="SYNTHETIC_OWNER_READ_DISABLED"):
        bridge_worker.run_job(fake_issue())


def test_mock_command_requires_test_process_even_if_flag_is_set(monkeypatch):
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(ValueError, match="SYNTHETIC_OWNER_READ_DISABLED"):
        bridge_worker.run_job(fake_issue())


def test_mock_command_never_accepts_external_url_or_new_goal(monkeypatch):
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    for issued in (
        fake_issue(url="https://crowdworks.jp/"),
        fake_issue(url="http://127.0.0.1:8002/login-ready"),
        fake_issue(goal="応募して"),
    ):
        with pytest.raises(ValueError, match="SYNTHETIC_OWNER_READ_CONTRACT_BLOCKED"):
            bridge_worker.run_job(issued)


@pytest.mark.skipif(not MOCK_E2E, reason="requires Chromium-enabled mock-only CI")
def test_issue_to_browser_to_sanitized_receipt(monkeypatch):
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    outcome = bridge_worker.run_job(fake_issue())
    assert outcome == {
        "run_id": "issue_4092",
        "mode": "owner_read_mock",
        "status": "PASS",
        "reason": "SYNTHETIC_READ_CONFIRMED",
        "title_count": 2,
        "vault_unchanged": True,
        "website_writes": 0,
        "paid_api_calls": 0,
        "real_site_calls": 0,
        "credential_values_included": False,
        "title_values_included": False,
    }
    public_json = json.dumps(outcome, ensure_ascii=False)
    for forbidden in ("架空案件A", "架空案件B",
                      "SYNTHETIC_ONLY_NOT_A_REAL_CREDENTIAL",
                      "PRIVATE_MOCK_SENTINEL_DO_NOT_PUBLISH",
                      "cookies", "storage_state", "crowdworks.jp"):
        assert forbidden not in public_json


@pytest.mark.skipif(not MOCK_E2E, reason="requires Chromium-enabled mock-only CI")
def test_private_titles_are_exact_and_vault_bytes_are_unchanged():
    result = run_mock_read(authenticated=True)
    assert result.status == "PASS"
    assert result.titles == (
        "架空案件A：CSVの空欄確認", "架空案件B：公開資料の整理"
    )
    assert result.vault_unchanged is True
    assert result.get_requests >= 1
    assert result.public_receipt()["title_count"] == 2
    assert "titles" not in result.public_receipt()


@pytest.mark.skipif(not MOCK_E2E, reason="requires Chromium-enabled mock-only CI")
def test_without_fake_login_cookie_read_is_blocked():
    result = run_mock_read(authenticated=False)
    assert result.status == "BLOCKED"
    assert result.titles == ()
    assert result.vault_unchanged is True
    assert result.public_receipt()["title_count"] == 0
