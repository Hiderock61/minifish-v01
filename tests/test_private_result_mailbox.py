"""Synthetic private-return contract: no real accounts or live Codespace.

The 'private receiver' is another Python caller holding a separate secret
inside the same test process. This does NOT prove a ChatGPT transport exists.
"""
import json
import os
import secrets

import pytest

import bridge_worker
from minifish.private_result_mailbox import PrivateResultMailbox

MOCK_E2E = os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") == "1"
GOAL = "READ_SYNTHETIC_JOB_TITLES"
TITLES = ("架空案件A：CSVの空欄確認", "架空案件B：公開資料の整理")


def issue(*, goal=GOAL, url=None):
    body = {"mode": "owner_private_delivery_mock", "goal": goal}
    if url is not None:
        body["url"] = url
    return {"number": 4101, "body": json.dumps(body, ensure_ascii=False)}


def fresh_box(*, clock=None):
    capability = secrets.token_urlsafe(32)
    kwargs = {"owner_capability": capability}
    if clock is not None:
        kwargs["clock"] = clock
    return PrivateResultMailbox(**kwargs), capability


def test_mailbox_claim_requires_independent_secret_and_single_use():
    box, secret = fresh_box()
    box.publish(job_id="issue_4101", titles=TITLES)
    with pytest.raises(ValueError, match="PRIVATE_ACCESS_DENIED"):
        box.claim(job_id="issue_4101", owner_capability="wrong" * 10)
    with pytest.raises(ValueError, match="PRIVATE_RESULT_UNAVAILABLE"):
        box.claim(job_id="issue_4102", owner_capability=secret)
    assert box.claim(job_id="issue_4101", owner_capability=secret) == TITLES
    with pytest.raises(ValueError, match="PRIVATE_RESULT_UNAVAILABLE"):
        box.claim(job_id="issue_4101", owner_capability=secret)


def test_mailbox_expires_exactly_at_deadline():
    now = [100.0]
    capability = secrets.token_urlsafe(32)
    box = PrivateResultMailbox(owner_capability=capability, ttl_seconds=2,
                               clock=lambda: now[0])
    box.publish(job_id="issue_99", titles=TITLES)
    now[0] = 102.0
    with pytest.raises(ValueError, match="PRIVATE_RESULT_EXPIRED"):
        box.claim(job_id="issue_99", owner_capability=capability)
    with pytest.raises(ValueError, match="PRIVATE_RESULT_UNAVAILABLE"):
        box.claim(job_id="issue_99", owner_capability=capability)


def test_mailbox_prevents_duplicate_or_unstructured_data():
    box, _ = fresh_box()
    box.publish(job_id="issue_4101", titles=TITLES)
    with pytest.raises(ValueError, match="PRIVATE_JOB_DUPLICATE"):
        box.publish(job_id="issue_4101", titles=TITLES)
    for bad in ((), ("",), (" bad ",), ("title\nCookie:fake",),
                ("x" * 121,), tuple("x" for _ in range(21)),
                ("valid", 8)):
        with pytest.raises(ValueError, match="PRIVATE_RESULT_SHAPE_INVALID"):
            box.publish(job_id="issue_4102", titles=bad)
    with pytest.raises(ValueError, match="PRIVATE_JOB_ID_INVALID"):
        box.publish(job_id="../vault", titles=TITLES)
    with pytest.raises(ValueError, match="PRIVATE_CAPABILITY_INVALID"):
        PrivateResultMailbox(owner_capability="1234")


def test_public_receipt_excludes_titles_counts_and_capability():
    box, capability = fresh_box()
    box.publish(job_id="issue_4101", titles=TITLES)
    receipt = box.public_receipt("issue_4101")
    assert receipt["status"] == "PRIVATE_RESULT_READY"
    assert "title_count" not in receipt
    assert "titles" not in receipt
    text = json.dumps(receipt, ensure_ascii=False)
    assert capability not in text
    for forbidden in ("架空案件", "PRIVATE_MOCK_SENTINEL",
                      "SYNTHETIC_ONLY_NOT_A_REAL_CREDENTIAL",
                      "token", "Cookie", "storage_state"):
        assert forbidden not in text


def test_bridge_private_mock_is_disabled_without_ci_flag(monkeypatch):
    box, _ = fresh_box()
    monkeypatch.delenv("MINIFISH_G1_PRIVATE_MOCK_E2E", raising=False)
    with pytest.raises(ValueError, match="PRIVATE_DELIVERY_MOCK_DISABLED"):
        bridge_worker.run_job(issue(), private_mailbox=box)


def test_bridge_private_mock_is_disabled_inside_real_codespaces(monkeypatch):
    box, _ = fresh_box()
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    monkeypatch.setenv("CODESPACE_NAME", "synthetic-will-still-block")
    with pytest.raises(ValueError, match="PRIVATE_DELIVERY_MOCK_DISABLED"):
        bridge_worker.run_job(issue(), private_mailbox=box)


def test_bridge_rejects_site_goal_and_missing_channel_before_browser(monkeypatch):
    box, _ = fresh_box()
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    for job in (issue(goal="応募する"),
                issue(url="https://crowdworks.jp/"),
                issue(url="http://127.0.0.1:8002/login-ready")):
        with pytest.raises(ValueError, match="PRIVATE_DELIVERY_CONTRACT_BLOCKED"):
            bridge_worker.run_job(job, private_mailbox=box)
    with pytest.raises(ValueError, match="PRIVATE_DELIVERY_CHANNEL_REQUIRED"):
        bridge_worker.run_job(issue())


@pytest.mark.skipif(not MOCK_E2E, reason="requires isolated Chromium mock-only CI")
def test_issue_to_private_one_time_receiver_with_zero_public_data(monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    box, capability = fresh_box()
    result = bridge_worker.run_job(issue(), private_mailbox=box)

    # What the PUBLIC GitHub comment could contain: status only, no data.
    assert result == {
        "mode": "owner_private_delivery_mock",
        "run_id": "issue_4101",
        "status": "PRIVATE_RESULT_READY",
        "private_values_included": False,
        "credentials_included": False,
        "access_capability_included": False,
        "website_writes": 0,
        "real_site_calls": 0,
        "paid_api_calls": 0,
    }
    report = json.dumps(result, ensure_ascii=False)
    for forbidden in (*TITLES, capability, "title_count", "cookies",
                      "PRIVATE_MOCK_SENTINEL_DO_NOT_PUBLISH",
                      "SYNTHETIC_ONLY_NOT_A_REAL_CREDENTIAL"):
        assert forbidden not in report

    # Only the separately authorized in-process receiver gets the titles.
    assert box.claim(job_id="issue_4101", owner_capability=capability) == TITLES
    with pytest.raises(ValueError, match="PRIVATE_RESULT_UNAVAILABLE"):
        box.claim(job_id="issue_4101", owner_capability=capability)
