"""MiniFish AI-planner promotion trial.

The real OpenAIPlanner may act ONLY on the fixed internal HTML test page.
No external navigation or account session is permitted, even if AI requests it.
Live API calls require TWO explicit gates, usable credentials and model.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json
import os
import re

from .command_tower import MiniFishCommandTower, Mission
from .models import Action
from .planner import OpenAIPlanner
from .runner import MiniFishRunner

MAX_AI_CALLS = 4
MAX_OUTPUT_TOKENS = 200
GOAL = (
    "Only in this built-in simulated page, open プロフィール, "
    "fill 表示名 with BONSAI_TEST, click 保存 and stop ONLY "
    "after you observe 保存完了. Do not navigate to any external website."
)


def classify_ai_failure(error: str | None) -> str:
    """Return an allowlisted diagnosis; never publish the raw SDK error.

    The exception stored privately by MiniFishRunner can contain request
    context. This classifier emits only a fixed category.
    """
    s = (error or "").lower()
    if not s:
        return "OUTPUT_NOT_VERIFIED"
    if any(x in s for x in ("insufficient_quota", "billing_hard_limit", "quota_exceeded")):
        return "API_QUOTA_OR_BILLING"
    if any(x in s for x in ("authenticationerror", "invalid_api_key", "error code: 401")):
        return "API_AUTHENTICATION"
    if any(x in s for x in ("permissiondeniederror", "error code: 403")):
        return "API_PERMISSION_DENIED"
    if any(x in s for x in ("ratelimiterror", "error code: 429")):
        return "API_429_RATE_OR_QUOTA_UNKNOWN"
    if any(x in s for x in ("apiconnectionerror", "apitimeouterror", "connecttimeout")):
        return "API_NETWORK_OR_TIMEOUT"
    if any(x in s for x in ("jsondecodeerror", "ai_action_outside_internal_allowlist")):
        return "AI_OUTPUT_FORMAT_OR_SAFETY_GATE"
    if "ai_call_limit" in s:
        return "API_CALL_LIMIT"
    return "UNCLASSIFIED_PRIVATE_ERROR"


class BoundedResponses:
    """Intercept each planned action BEFORE an API call is made."""
    def __init__(self, downstream: Any, limit: int = MAX_AI_CALLS):
        self.downstream = downstream
        self.limit = limit
        self.calls = 0

    def create(self, **kwargs: Any) -> Any:
        if self.calls >= self.limit:
            raise RuntimeError("AI_CALL_LIMIT")
        # Don't send unexpectedly large observations or unbounded output.
        if len(json.dumps(kwargs.get("input", []), ensure_ascii=False)) > 17000:
            raise RuntimeError("AI_INPUT_TOO_LONG")
        kwargs["store"] = False
        kwargs["max_output_tokens"] = MAX_OUTPUT_TOKENS
        self.calls += 1
        return self.downstream.create(**kwargs)


class SafeAIActionPlanner:
    """Existing OpenAIPlanner + deterministic output policy before action."""
    def __init__(self, delegate: OpenAIPlanner, meter: BoundedResponses):
        self.delegate = delegate
        self.meter = meter

    def next_action(self, goal: str, observation: Any,
                    history: list[dict[str, Any]],
                    human_facts: list[str] | None = None) -> Action:
        action = self.delegate.next_action(goal, observation, history, human_facts)
        text = str(observation.text_excerpt or "")
        aria = str(observation.aria_snapshot or "")
        if action.type == "click" and action.role == "button":
            if action.name == "プロフィール" and "プロフィール" in text + aria:
                return action
            if action.name == "保存" and "保存" in text + aria:
                return action
        if (action.type == "fill" and action.role == "textbox"
                and action.name == "表示名" and action.value == "BONSAI_TEST"
                and "表示名" in text + aria):
            return action
        if action.type == "done" and "保存完了" in text:
            return action
        if action.type == "fail":
            return action
        raise ValueError("AI_ACTION_OUTSIDE_INTERNAL_ALLOWLIST")


class OfflineResponses:
    """Static JSON-shaped model fixture. NOT an AI model."""
    def __init__(self):
        self.i = 0
        self.actions = [
            {"type": "click", "role": "button", "name": "プロフィール"},
            {"type": "fill", "role": "textbox", "name": "表示名",
             "value": "BONSAI_TEST"},
            {"type": "click", "role": "button", "name": "保存"},
            {"type": "done", "result": "internal simulation saved"},
        ]

    def create(self, **kwargs: Any) -> Any:
        next_action = self.actions[self.i]
        self.i += 1
        return SimpleNamespace(output_text=json.dumps(next_action, ensure_ascii=False))


def build_delegate(mode: str) -> tuple[SafeAIActionPlanner, BoundedResponses]:
    if mode == "mock":
        # Exercise the REAL OpenAIPlanner JSON parsing path, but use no network.
        delegate = OpenAIPlanner.__new__(OpenAIPlanner)
        delegate.model = "offline-static-fixture-not-ai"
        meter = BoundedResponses(OfflineResponses())
    elif mode == "live":
        from openai import OpenAI
        delegate = OpenAIPlanner.__new__(OpenAIPlanner)
        delegate.model = os.environ["OPENAI_MODEL"]
        # No SDK retries, to preserve the hard request cap.
        meter = BoundedResponses(OpenAI(max_retries=0, timeout=25).responses)
    else:
        raise ValueError("INVALID_MODE")
    delegate.client = SimpleNamespace(responses=meter)
    return SafeAIActionPlanner(delegate, meter), meter


def run_ai_tower_trial(job_id: str, *, mode: str = "mock",
                       approved: bool = False,
                       output_root: str = "ai_tower_runs") -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", job_id):
        return {"state": "STOP", "reason": "INVALID_JOB_ID", "api_calls": 0}
    if mode not in ("mock", "live"):
        return {"state": "STOP", "reason": "INVALID_MODE", "api_calls": 0}
    tower_preflight = MiniFishCommandTower.preflight(
        Mission(job_id=job_id, goal=GOAL, route="internal_demo",
                action_class="local_demo", max_paid_calls=0)
    )
    if tower_preflight.state != "PASS":
        return {"state": tower_preflight.state, "reason": tower_preflight.reason,
                "api_calls": 0}
    if mode == "live":
        if not approved or os.getenv("MINIFISH_AI_LIVE_CONSENT") != "yes":
            return {"state": "HUMAN", "reason": "LIVE_API_APPROVAL_REQUIRED",
                    "api_calls": 0}
        if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"):
            return {"state": "HUMAN", "reason": "API_KEY_OR_MODEL_REQUIRED",
                    "api_calls": 0}

    from demo_run import DEMO_HTML
    planner, meter = build_delegate(mode)
    root = Path(output_root) / job_id
    root.mkdir(parents=True, exist_ok=True)
    runner = MiniFishRunner(
        planner, headless=True, max_steps=MAX_AI_CALLS,
        max_duration_seconds=160, profile_path=None,
        capture_dir=str(root / "captures"),
        log_path=str(root / "private_run.json"),
    )
    state = runner.run(GOAL, start_url="about:blank", start_html=DEMO_HTML)
    names = [x.action_type for x in state.ledger]
    saved = any("保存完了" in str(e.observation.get("text_excerpt", ""))
                for e in state.events)
    guard = all(x.decision == "PASS" for x in state.ledger)
    success = state.status == "COMPLETED" and saved and guard and names == [
        "click", "fill", "click", "done"
    ]
    public = {
        "state": "COMPLETE" if success else "STOP",
        "result": "PASS" if success else "FAIL",
        "mode": mode,
        "planner": "OpenAIPlanner/Responses" if mode == "live"
                   else "OpenAIPlanner JSON parser + static offline fixture",
        "live_ai_verified": bool(success and mode == "live"),
        "run_id": state.run_id,
        "steps": state.step_count,
        "api_calls": meter.calls if mode == "live" else 0,
        "mock_model_calls": meter.calls if mode == "mock" else 0,
        "saved_visible": saved,
        "supervisor_pass": guard,
        "external_web_navigation": False,
        "error_layer": None if success else (
            "AI_ACTION_OR_RUNNER_FAILED" if state.error else "OUTPUT_NOT_VERIFIED"),
        "error_code": None if success else classify_ai_failure(state.error),
    }
    (root / "public_report.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return public
