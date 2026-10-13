"""Single-turn official API transport for MiniFish/BONSaY, not ChatGPT web UI."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
import hashlib


@dataclass(frozen=True)
class Delivery:
    status: str
    transport: str
    model: str
    response_id: str | None
    raw_text: str
    text_sha256: str
    usage_input_tokens: int | None
    usage_output_tokens: int | None
    error_layer: str | None

    def public_summary(self) -> dict[str, Any]:
        """Public issues must not contain generated raw text."""
        d = asdict(self)
        d.pop("raw_text")
        return d


class MockResponsesClient:
    """Deterministic no-cost stub; never contacts any outside service."""
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    class _Response:
        id = "mock_bonsai_g2"
        status = "completed"
        output_text = "READY"
        usage = None

    class _Responses:
        def __init__(self, outer: "MockResponsesClient") -> None:
            self.outer = outer

        def create(self, **kwargs: Any) -> "MockResponsesClient._Response":
            self.outer.calls.append(kwargs)
            return MockResponsesClient._Response()

    @property
    def responses(self) -> "MockResponsesClient._Responses":
        return MockResponsesClient._Responses(self)


def send_one_prompt(client: Any, *, model: str, prompt: str,
                    transport: str = "openai_responses_api", max_output_tokens: int = 128) -> Delivery:
    """One request only, no retry. Return whole reply locally; sanitize public summary."""
    if not model or not model.strip():
        raise ValueError("model_required")
    if not prompt or not prompt.strip():
        raise ValueError("prompt_required")
    if not 1 <= max_output_tokens <= 256:
        raise ValueError("max_output_tokens_out_of_range")
    try:
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            max_output_tokens=max_output_tokens,
            store=False,
        )
    except Exception as exc:
        # Never echo SDK exception text, which can include private request context.
        return Delivery("FAIL", transport, model, None, "", "", None, None,
                        "API_" + type(exc).__name__)
    raw_text = getattr(response, "output_text", "") or ""
    remote_status = getattr(response, "status", None)
    accepted = bool(raw_text.strip()) and remote_status in (None, "completed")
    usage = getattr(response, "usage", None)
    return Delivery(
        "PASS" if accepted else "UNKNOWN", transport, model,
        getattr(response, "id", None), raw_text,
        hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else "",
        getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
        None if accepted else "EMPTY_OR_INCOMPLETE_RESPONSE",
    )
