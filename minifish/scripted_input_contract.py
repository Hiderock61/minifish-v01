"""Strict, offline-only GitHub Issue -> ScriptedPlanner input adapter (v1).

This module ONLY validates an Issue payload, converts the fixed internal
fixture's approved steps into Action objects, and verifies a synthetic result.
It does not run a browser, contact GitHub, process secrets, or activate API AI.

Staged prototype for base commit 01427b9088c384263b4875aeff5351f63db36b8b.
Not wired into bridge_worker.py or any Actions workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .models import Action

MODE = "scripted_fixture_v1"
TITLE_PREFIX = "[MINIFISH JOB]"
TARGET = "internal_profile_fixture"
MAX_BODY_BYTES = 4000
MAX_GOAL_CHARS = 200
# Deliberately ASCII-only: the existing HTML fixture uses innerHTML.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}\Z", re.ASCII)
ACTION_TYPES = ("click", "fill", "click", "done")


class InputContractError(ValueError):
    """Error codes only: never include raw Issue values in messages."""


@dataclass(frozen=True)
class ScriptedFixtureJob:
    issue_number: int
    goal: str
    display_name: str
    actions: tuple[Action, ...]


def _unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise InputContractError("DUPLICATE_JSON_KEY")
        out[key] = value
    return out


def _reject_json_constant(value: str) -> None:
    raise InputContractError("INVALID_JSON_CONSTANT")


def _strict_json(body: str) -> Any:
    try:
        return json.loads(body, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_json_constant)
    except InputContractError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InputContractError("INVALID_JSON") from None


def decode_issue_json(raw: str) -> Any:
    """Shared strict JSON parser for Bridge preflight (duplicate keys forbidden)."""
    return _strict_json(raw)


def _exact_step(actual: Any, expected: dict[str, str], *, fill: bool = False) -> str | None:
    if not isinstance(actual, dict):
        raise InputContractError("INVALID_STEP_TYPE")
    expected_keys = set(expected) | ({"value"} if fill else set())
    if set(actual) != expected_keys:
        raise InputContractError("INVALID_STEP_FIELDS")
    if any(type(actual[k]) is not str or actual[k] != v for k, v in expected.items()):
        raise InputContractError("INVALID_STEP_ACTION")
    if fill:
        value = actual["value"]
        if type(value) is not str or NAME_PATTERN.fullmatch(value) is None:
            raise InputContractError("INVALID_DISPLAY_NAME")
        return value
    return None


def parse_scripted_fixture_issue(issue: dict[str, Any], *, owner: str) -> ScriptedFixtureJob:
    """Validate the entire untrusted Issue BEFORE constructing a planner.

    Note: the owner check here trusts the GitHub-authenticated transport
    metadata. A raw JSON body claiming an owner is never authority by itself.
    """
    if not isinstance(issue, dict):
        raise InputContractError("INVALID_ISSUE")
    number = issue.get("number")
    if type(number) is not int or not 1 <= number <= 2_000_000_000:
        raise InputContractError("INVALID_ISSUE_NUMBER")
    title = issue.get("title")
    if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
        raise InputContractError("INVALID_ISSUE_TITLE")
    author = issue.get("author")
    if not isinstance(owner, str) or not owner or not isinstance(author, dict) or author.get("login") != owner:
        raise InputContractError("ISSUE_OWNER_NOT_AUTHORIZED")
    body = issue.get("body")
    if not isinstance(body, str):
        raise InputContractError("INVALID_BODY_SIZE")
    try:
        body_bytes = body.encode("utf-8")
    except UnicodeError:
        raise InputContractError("INVALID_BODY_ENCODING") from None
    if len(body_bytes) > MAX_BODY_BYTES:
        raise InputContractError("INVALID_BODY_SIZE")
    payload = _strict_json(body)
    if not isinstance(payload, dict):
        raise InputContractError("INVALID_PAYLOAD")
    if set(payload) != {"contract_version", "mode", "goal", "target", "steps"}:
        raise InputContractError("UNEXPECTED_FIELDS")
    # type() excludes boolean True, despite bool being an int subclass.
    if type(payload["contract_version"]) is not int or payload["contract_version"] != 1:
        raise InputContractError("INVALID_CONTRACT_VERSION")
    if payload["mode"] != MODE or type(payload["mode"]) is not str:
        raise InputContractError("MODE_ESCALATION_BLOCKED")
    if type(payload["target"]) is not str or payload["target"] != TARGET:
        raise InputContractError("TARGET_NOT_ALLOWLISTED")
    goal = payload["goal"]
    if type(goal) is not str or not 1 <= len(goal.strip()) <= MAX_GOAL_CHARS:
        raise InputContractError("INVALID_GOAL")
    steps = payload["steps"]
    if type(steps) is not list or len(steps) != 4:
        raise InputContractError("INVALID_STEPS")
    _exact_step(steps[0], {"type": "click", "role": "button", "name": "プロフィール"})
    value = _exact_step(steps[1], {"type": "fill", "role": "textbox", "name": "表示名"}, fill=True)
    _exact_step(steps[2], {"type": "click", "role": "button", "name": "保存"})
    _exact_step(steps[3], {"type": "done"})
    assert isinstance(value, str)
    # Construct Actions only after *all* fields have passed the allowlist.
    actions = (
        Action(type="click", role="button", name="プロフィール"),
        Action(type="fill", role="textbox", name="表示名", value=value),
        Action(type="click", role="button", name="保存"),
        Action(type="done"),
    )
    return ScriptedFixtureJob(number, goal.strip(), value, actions)


def verify_scripted_fixture_state(state: Any, job: ScriptedFixtureJob) -> dict[str, Any]:
    """Inspect final observed page; never equate a planner's 'done' with save.

    Call this only after a Runner operated on the trusted, built-in DEMO_HTML.
    Report no raw page text or user-supplied values to an Issue.
    """
    ledger = getattr(state, "ledger", None)
    events = getattr(state, "events", None)
    last = events[-1] if isinstance(events, list) and events else None
    observation = getattr(last, "observation", None) if last else None
    text = observation.get("text_excerpt", "") if isinstance(observation, dict) else ""
    lines = [x.strip() for x in text.splitlines()] if isinstance(text, str) else []
    correct_sequence = (
        isinstance(ledger, list) and len(ledger) == 4
        and tuple(getattr(item, "action_type", None) for item in ledger) == ACTION_TYPES
        and all(getattr(item, "decision", None) == "PASS" for item in ledger)
    )
    # Independent observation of the result, not just a declared Action.done.
    saved_visible = "保存完了" in lines and job.display_name in lines
    completed = getattr(state, "status", None) == "COMPLETED"
    checked = bool(correct_sequence and saved_visible and completed)
    return {
        "status": "PASS" if checked else "FAIL",
        "reason": "FIXTURE_RESULT_VERIFIED" if checked else "FIXTURE_RESULT_NOT_VERIFIED",
        "issue_number": job.issue_number,
        "step_count": len(ledger) if isinstance(ledger, list) else 0,
        "guard_sequence_pass": bool(correct_sequence),
        "saved_visible": bool(saved_visible),
        "runner_completed": bool(completed),
        # Runtime I/O is not proven by examining a RunState alone.
        "runtime_io_verification": "NOT_MEASURED",
    }
