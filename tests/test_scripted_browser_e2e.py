"""Offline-only REAL Chromium browser end-to-end for the staged scripted fixture.

No networked site, token, GitHub API, OpenAI API, or authenticated session.
Tests only the baseline MiniFishRunner+PlaywrightBrowser from 01427b9.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

import bridge_worker

pytestmark = pytest.mark.skipif(
    os.getenv("MINIFISH_BROWSER_E2E") != "1",
    reason="Explicit opt-in required for real local Chromium E2E",
)

from minifish.browser import PlaywrightBrowser
from minifish.scripted_input_contract import MODE


def _issue(number, name="MFTEST_001"):
    return {
        "number": number,
        "title": "[MINIFISH JOB] scripted fixture offline-only acceptance",
        "author": {"login": "Hiderock61"},
        "body": json.dumps({
            "contract_version": 1,
            "mode": MODE,
            "goal": "Save the synthetic profile display name only",
            "target": "internal_profile_fixture",
            "steps": [
                {"type": "click", "role": "button", "name": "プロフィール"},
                {"type": "fill", "role": "textbox", "name": "表示名", "value": name},
                {"type": "click", "role": "button", "name": "保存"},
                {"type": "done"},
            ],
        }, ensure_ascii=False),
    }


@pytest.fixture(autouse=True)
def offline_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIFISH_ENABLE_SCRIPTED_FIXTURE_V1", "1")
    system_chromium = shutil.which("chromium") or shutil.which("google-chrome")
    if system_chromium:
        monkeypatch.setenv("MINIFISH_CHROMIUM_PATH", system_chromium)
    else:
        monkeypatch.delenv("MINIFISH_CHROMIUM_PATH", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(bridge_worker, "RUN_ROOT", tmp_path / "runs")


def test_real_chromium_injected_issue_value_and_guard(monkeypatch):
    executed = []
    page_requests = []
    original_execute = PlaywrightBrowser.execute
    original_enter = PlaywrightBrowser.__enter__

    def monitored_enter(self):
        browser = original_enter(self)
        assert self.profile_path is None and self.session_vault is None
        assert self.page is not None
        # Fail closed on any http(s) request by the synthetic page.
        self.page.route("**/*", lambda route: route.abort())
        self.page.on("request", lambda request: page_requests.append(request.url))
        return browser

    def monitored_execute(self, action):
        executed.append((action.type, action.name, action.value))
        return original_execute(self, action)

    monkeypatch.setattr(PlaywrightBrowser, "__enter__", monitored_enter)
    monkeypatch.setattr(PlaywrightBrowser, "execute", monitored_execute)

    for number, display in [(801, "MFTEST_001"), (802, "MFTEST_002")]:
        issue = _issue(number, display)
        job = bridge_worker.preflight_issue(issue)
        assert job is not None and job.display_name == display
        assert bridge_worker.claim_scripted_issue(number)
        result = bridge_worker.run_job(issue, validated_scripted_job=job)
        assert result["status"] == "PASS", result
        assert result["step_count"] == 4
        assert result["guard_sequence_pass"] is True
        assert result["saved_visible"] is True
        assert result["runner_completed"] is True
        assert result["runtime_io_verification"] == "NOT_MEASURED"
    assert [x[0] for x in executed] == ["click", "fill", "click"] * 2
    assert [x[2] for x in executed if x[0] == "fill"] == ["MFTEST_001", "MFTEST_002"]
    assert page_requests == [], page_requests


def test_invalid_steps_block_before_browser(monkeypatch):
    issue = _issue(803)
    body = json.loads(issue["body"])
    body["steps"].insert(2, {"type": "press", "key": "Enter"})
    issue["body"] = json.dumps(body)
    def forbid_enter(self):
        raise AssertionError("BROWSER_MUST_NOT_START_FOR_INVALID_INPUT")
    monkeypatch.setattr(PlaywrightBrowser, "__enter__", forbid_enter)
    with pytest.raises(ValueError):
        bridge_worker.preflight_issue(issue)
    assert not (bridge_worker.RUN_ROOT / "issue_803").exists()


def test_done_without_actual_save_is_not_pass(monkeypatch):
    import cloud_api
    # The same buttons exist but Save does not update text. Real clicks occur.
    bad_fixture = cloud_api.DEMO_HTML.replace(
        'document.body.innerHTML = `<h1>保存完了</h1><p>${name}</p>`;',
        'document.body.innerHTML = `<h1>保存保留</h1><p>${name}</p>`;',
    )
    assert bad_fixture != cloud_api.DEMO_HTML
    monkeypatch.setattr(cloud_api, "DEMO_HTML", bad_fixture)
    issue = _issue(804, "MFTEST_004")
    job = bridge_worker.preflight_issue(issue)
    assert bridge_worker.claim_scripted_issue(804)
    result = bridge_worker.run_job(issue, validated_scripted_job=job)
    assert result["status"] == "FAIL", result
    assert result["runner_completed"] is True
    assert result["guard_sequence_pass"] is True
    assert result["saved_visible"] is False


def test_real_chromium_via_bridge_main_mocked_transport(monkeypatch):
    issue = _issue(805, "MFTEST_MAIN")
    calls = []
    monkeypatch.setattr(bridge_worker.issue_transport, "transport_ready", lambda: "TEST_OFFLINE")
    monkeypatch.setattr(bridge_worker, "list_jobs", lambda: [issue])
    monkeypatch.setattr(bridge_worker, "comment", lambda number, body: calls.append(("comment", number, body)))
    monkeypatch.setattr(bridge_worker, "close", lambda number: calls.append(("close", number)))

    class OneIterationComplete(Exception):
        pass

    monkeypatch.setattr(bridge_worker.time, "sleep", lambda secs: (_ for _ in ()).throw(OneIterationComplete()))
    with pytest.raises(OneIterationComplete):
        bridge_worker.main()
    assert [x[0] for x in calls] == ["comment", "comment", "close"], calls
    assert "accepted" in calls[0][2]
    assert '"status": "PASS"' in calls[1][2]
    assert "MFTEST_MAIN" not in calls[1][2], "No raw user-supplied input in Issue result"
    assert calls[2] == ("close", 805)

    # Another process invocation in the same RUN_ROOT must not re-execute the claimed job.
    before = list(calls)
    with pytest.raises(OneIterationComplete):
        bridge_worker.main()
    assert calls == before
