"""Offline tests for the ChatGPT -> Issue -> read-only MiniFish path."""
import json
from pathlib import Path
from types import SimpleNamespace

import bridge_worker
from minifish.command_tower import MiniFishCommandTower
from minifish import readonly_probe


def test_readonly_gate_allows_only_single_public_fixture():
    allow = MiniFishCommandTower.preflight_public_readonly(
        "issue_100", "公開ページのタイトルを確認", "https://example.com/"
    )
    assert allow.state == "PASS"
    for url in (
        "https://example.com.evil.test/", "http://example.com/",
        "https://example.com/login", "https://other.example/",
        "file:///etc/passwd", "https://example.com/?token=123"
    ):
        assert MiniFishCommandTower.preflight_public_readonly(
            "issue_100", "read only", url
        ).state == "STOP"


def test_readonly_gate_rejects_empty_or_too_long_goal():
    for goal in ("", " ", "x" * 201):
        assert MiniFishCommandTower.preflight_public_readonly(
            "issue_100", goal, "https://example.com/"
        ).state == "STOP"


def test_existing_bridge_worker_routes_read_only_without_agent(monkeypatch):
    seen = {}
    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"status": "PASS", "api_calls": 0}
    monkeypatch.setattr(readonly_probe, "run_public_readonly", fake_run)
    payload = {
        "number": 101,
        "body": json.dumps({"mode": "read_only",
                            "url": "https://example.com/",
                            "goal": "公開タイトル確認"}, ensure_ascii=False),
    }
    result = bridge_worker.run_job(payload)
    assert result["status"] == "PASS"
    assert seen["job_id"] == "issue_101"
    assert seen["goal"] == "公開タイトル確認"
    assert seen["url"] == "https://example.com/"


def test_invalid_site_never_launches_browser(monkeypatch, tmp_path):
    class ShouldNotRun:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Browser must not start")
    monkeypatch.setattr(readonly_probe, "MiniFishRunner", ShouldNotRun)
    result = readonly_probe.run_public_readonly(
        job_id="issue_1", goal="read", url="https://not-allowed.invalid/",
        run_dir=tmp_path,
    )
    assert result["status"] == "BLOCKED"
    assert result["api_calls"] == result["external_writes"] == 0


def test_public_evidence_requires_real_observation_and_supervisor(monkeypatch, tmp_path):
    class FakeRunner:
        def __init__(self, planner, **kwargs):
            assert kwargs["profile_path"] is None
            assert kwargs["capture_dir"] is None
            assert kwargs["max_steps"] == 1
        def run(self, **kwargs):
            assert kwargs["start_url"] == "https://example.com/"
            return SimpleNamespace(
                run_id="mock_unit",
                status="COMPLETED", step_count=1,
                events=[SimpleNamespace(observation={
                    "url": "https://example.com/", "title": "Example Domain",
                    "text_excerpt": "This domain is for use in documentation examples.",
                })],
                ledger=[SimpleNamespace(decision="PASS", action_type="done")],
            )
    monkeypatch.setattr(readonly_probe, "MiniFishRunner", FakeRunner)
    result = readonly_probe.run_public_readonly(
        job_id="issue_20", goal="read", url="https://example.com/",
        run_dir=tmp_path,
    )
    assert result["status"] == "PASS"
    assert result["title"] == "Example Domain"
    assert result["browser_actions_executed"] == 0


def test_done_without_page_evidence_is_not_success(monkeypatch, tmp_path):
    class FakeRunner:
        def __init__(self, *args, **kwargs):
            pass
        def run(self, **kwargs):
            return SimpleNamespace(
                run_id="mock_unit",
                status="COMPLETED", step_count=1,
                events=[SimpleNamespace(observation={
                    "url": "https://example.com/", "title": "403 Forbidden",
                    "text_excerpt": "403 Forbidden"
                })],
                ledger=[SimpleNamespace(decision="PASS", action_type="done")],
            )
    monkeypatch.setattr(readonly_probe, "MiniFishRunner", FakeRunner)
    result = readonly_probe.run_public_readonly(
        job_id="issue_21", goal="read", url="https://example.com/",
        run_dir=tmp_path,
    )
    assert result["status"] == "FAIL"
    assert result["public_excerpt"] == ""
    assert result["supervisor_pass"] is False
