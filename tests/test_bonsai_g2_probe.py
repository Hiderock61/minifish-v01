from types import SimpleNamespace
import pytest

from minifish.chatgpt_api_adapter import MockResponsesClient, send_one_prompt
from minifish.bonsai_g2_probe import run_probe


def test_mock_one_call_and_full_text():
    client = MockResponsesClient()
    result = send_one_prompt(client, model="mock", prompt="test", transport="mock_only")
    assert result.status == "PASS"
    assert result.raw_text == "READY"
    assert len(client.calls) == 1
    assert client.calls[0]["store"] is False
    assert client.calls[0]["max_output_tokens"] == 128
    assert "raw_text" not in result.public_summary()


def test_no_empty_prompt_or_unknown_model():
    client = MockResponsesClient()
    with pytest.raises(ValueError):
        send_one_prompt(client, model="", prompt="test")
    with pytest.raises(ValueError):
        send_one_prompt(client, model="x", prompt=" ")
    with pytest.raises(ValueError):
        send_one_prompt(client, model="x", prompt="test", max_output_tokens=300)
    assert not client.calls


def test_incomplete_response_is_unknown():
    class EmptyClient:
        responses = SimpleNamespace(create=lambda **_: SimpleNamespace(status="completed", output_text="", id="response"))
    assert send_one_prompt(EmptyClient(), model="test", prompt="ping").status == "UNKNOWN"


def test_api_exceptions_are_sanitized():
    class FailClient:
        responses = SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(ValueError("secret token")))
    result = send_one_prompt(FailClient(), model="test", prompt="ping")
    assert result.error_layer == "API_ValueError"
    assert "secret token" not in str(result)


def test_mock_probe_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    report = run_probe("mock", output_dir=tmp_path)
    assert report["status"] == "PASS"
    assert report["api_called"] is False
    assert (tmp_path / "result.json").exists()
    assert report["checks"]["fixed_ready_returned"] is True


def test_live_requires_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIFISH_G2_REAL_API_CONSENT", raising=False)
    with pytest.raises(PermissionError):
        run_probe("live", allow_billable=False, output_dir=tmp_path)
    with pytest.raises(PermissionError):
        run_probe("live", allow_billable=True, output_dir=tmp_path)
