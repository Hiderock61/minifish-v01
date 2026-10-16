from types import SimpleNamespace
import os
import pytest

from minifish.ai_tower import (
    BoundedResponses, OfflineResponses, SafeAIActionPlanner,
    build_delegate, run_ai_tower_trial, classify_ai_failure,
)
from minifish.models import Action, Observation


def test_response_meter_caps_and_disables_storage():
    class Spy:
        def __init__(self):
            self.kwargs = []
        def create(self, **kw):
            self.kwargs.append(kw)
            return SimpleNamespace(output_text='{"type":"done"}')
    spy = Spy()
    meter = BoundedResponses(spy, limit=2)
    for _ in range(2):
        meter.create(model="mock", input=[])
    assert all(x["store"] is False and x["max_output_tokens"] == 200
               for x in spy.kwargs)
    with pytest.raises(RuntimeError, match="AI_CALL_LIMIT"):
        meter.create(model="mock", input=[])
    assert len(spy.kwargs) == 2


def test_bounded_input():
    meter = BoundedResponses(OfflineResponses())
    with pytest.raises(RuntimeError, match="AI_INPUT_TOO_LONG"):
        meter.create(input=[{"text": "x" * 18000}])


def test_reuse_existing_openai_planner_parser_with_offline_fixture():
    p, meter = build_delegate("mock")
    observation = Observation("about:blank", "mock", "- button プロフィール", "プロフィール")
    action = p.next_action("demo", observation, [])
    assert action.type == "click" and action.name == "プロフィール"
    assert meter.calls == 1


def test_ai_must_not_navigate_external():
    class EscapePlanner:
        def next_action(self, *args):
            return Action(type="goto", url="https://example.com")
    obs = Observation("about:blank", "Demo", "", "プロフィール")
    with pytest.raises(ValueError, match="AI_ACTION_OUTSIDE_INTERNAL_ALLOWLIST"):
        SafeAIActionPlanner(EscapePlanner(), BoundedResponses(OfflineResponses())).next_action(
            "try", obs, [])


def test_early_done_is_rejected():
    class TooEarly:
        def next_action(self, *args):
            return Action(type="done", result="done")
    obs = Observation("about:blank", "Demo", "", "プロフィール")
    with pytest.raises(ValueError, match="AI_ACTION_OUTSIDE_INTERNAL_ALLOWLIST"):
        SafeAIActionPlanner(TooEarly(), BoundedResponses(OfflineResponses())).next_action(
            "try", obs, [])


def test_live_denied_before_key_or_network(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIFISH_AI_LIVE_CONSENT", raising=False)
    r = run_ai_tower_trial("G2_DENIED", mode="live", approved=True,
                           output_root=str(tmp_path))
    assert r["state"] == "HUMAN"
    assert r["api_calls"] == 0
    assert not list(tmp_path.iterdir())


def test_invalid_job_id(tmp_path):
    r = run_ai_tower_trial("../../unsafe", mode="mock",
                           output_root=str(tmp_path))
    assert r["state"] == "STOP"
    assert r["api_calls"] == 0


@pytest.mark.skipif(os.getenv("MINIFISH_BROWSER_E2E") != "1",
                    reason="Chromium present only in dedicated E2E runner")
def test_existing_planner_parser_via_guard_and_real_browser(tmp_path):
    r = run_ai_tower_trial("TOWER_AI_MOCK", mode="mock", output_root=str(tmp_path))
    assert r["state"] == "COMPLETE", r
    assert r["steps"] == 4
    assert r["supervisor_pass"] and r["saved_visible"]
    assert r["mock_model_calls"] == 4
    assert r["api_calls"] == 0
    assert r["live_ai_verified"] is False


def test_public_api_failure_diagnosis_is_allowlisted_and_secret_free():
    assert classify_ai_failure("RateLimitError: insufficient_quota") == "API_QUOTA_OR_BILLING"
    assert classify_ai_failure("AuthenticationError: invalid_api_key") == "API_AUTHENTICATION"
    assert classify_ai_failure("RateLimitError: Error code: 429") == "API_429_RATE_OR_QUOTA_UNKNOWN"
    assert classify_ai_failure("JSONDecodeError") == "AI_OUTPUT_FORMAT_OR_SAFETY_GATE"
    assert classify_ai_failure("some private secret-like content") == "UNCLASSIFIED_PRIVATE_ERROR"
    assert classify_ai_failure(None) == "OUTPUT_NOT_VERIFIED"
