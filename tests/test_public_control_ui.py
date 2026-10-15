"""iPhone control-seat public READ regression without network or billable API."""
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

import cloud_api
from minifish import readonly_probe


def test_iphone_control_contains_safe_read_picker():
    html = cloud_api.CONTROL_HTML
    assert '<option value="public_read">' in html
    assert 'sitePicker' in html
    assert 'https://docs.python.org/3/' in html
    assert 'mode === \'public_read\'' in html


@pytest.mark.asyncio
async def test_cloud_api_rejects_unregistered_url_without_launching():
    request = cloud_api.RunRequest(
        mode="public_read", goal="公開観測", url="http://127.0.0.1:8000/admin"
    )
    with pytest.raises(HTTPException) as exc:
        await cloud_api.create_run(request, BackgroundTasks())
    assert exc.value.status_code == 400
    assert exc.value.detail == "URL_NOT_ALLOWLISTED"


@pytest.mark.asyncio
async def test_cloud_api_accepts_public_read_and_reports_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_api, "RUN_ROOT", tmp_path)
    seen = {}
    def fake_run(**kwargs):
        seen.update(kwargs)
        return {
            "status": "PASS", "title": "Example Domain",
            "observed_url": "https://example.com/",
            "public_excerpt": "Official public documentation sample.",
            "reason": "PUBLIC_PAGE_OBSERVED", "steps": 1,
            "evidence_checks": {"url_match": True, "title_match": True},
        }
    monkeypatch.setattr(readonly_probe, "run_public_readonly", fake_run)
    request = cloud_api.RunRequest(
        mode="public_read", goal="公開サンプル確認", url="https://example.com/"
    )
    initial = await cloud_api.create_run(request, BackgroundTasks())
    assert initial["status"] == "PENDING"
    cloud_api.run_worker(initial["run_id"], request)
    result = await cloud_api.get_run(initial["run_id"])
    assert result["status"] == "COMPLETED"
    assert result["mode"] == "public_read"
    assert result["current_url"] == "https://example.com/"
    assert result["step_count"] == 1
    assert seen["run_id"] == initial["run_id"]
    assert callable(seen["should_stop"])
    assert result["events"] == []


def test_brower_run_cancellation_before_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_api, "RUN_ROOT", tmp_path)
    run_id = "run_cancel_before_launch"
    cloud_api.CANCEL_FLAGS[run_id] = True
    called = []
    monkeypatch.setattr(readonly_probe, "run_public_readonly", lambda **kwargs: called.append(1))
    cloud_api.run_worker(run_id, cloud_api.RunRequest(
        mode="public_read", goal="read", url="https://example.com/"
    ))
    assert called == []
