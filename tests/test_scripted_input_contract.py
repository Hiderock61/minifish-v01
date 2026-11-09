"""Offline contract tests; no runner, browser, GitHub transport, or API calls."""
import json
from dataclasses import dataclass
from copy import deepcopy

import pytest
from minifish.scripted_input_contract import (
    InputContractError, parse_scripted_fixture_issue, verify_scripted_fixture_state,
)
from minifish.planner import ScriptedPlanner
from minifish.models import Observation
from minifish.guard import SupervisorGate

OWNER = "Hiderock61"


def payload(name="MFTEST_001"):
    return {
        "contract_version": 1,
        "mode": "scripted_fixture_v1",
        "goal": "架空プロフィールの表示名を保存する",
        "target": "internal_profile_fixture",
        "steps": [
            {"type": "click", "role": "button", "name": "プロフィール"},
            {"type": "fill", "role": "textbox", "name": "表示名", "value": name},
            {"type": "click", "role": "button", "name": "保存"},
            {"type": "done"},
        ],
    }


def issue(p=None):
    return {"number": 42, "title": "[MINIFISH JOB] fixture v1",
            "author": {"login": OWNER},
            "body": json.dumps(payload() if p is None else p, ensure_ascii=False)}


def reject(p, code=None):
    with pytest.raises(InputContractError) as ex:
        parse_scripted_fixture_issue(issue(p), owner=OWNER)
    if code is not None:
        assert str(ex.value) == code


@pytest.mark.parametrize("name", ["MFTEST_001", "MFTEST_002", "A", "ab-2_X"])
def test_valid_issue_builds_original_action_contract_and_planner(name):
    job = parse_scripted_fixture_issue(issue(payload(name)), owner=OWNER)
    assert job.issue_number == 42 and job.display_name == name
    assert tuple(a.type for a in job.actions) == ("click", "fill", "click", "done")
    assert job.actions[1].value == name
    planner = ScriptedPlanner(job.actions)
    obs = Observation(url="about:blank", title="Mock", aria_snapshot="", text_excerpt="")
    assert [planner.next_action(job.goal, obs, []).type for _ in range(4)] == ["click", "fill", "click", "done"]
    assert planner.next_action(job.goal, obs, []).type == "done"
    guard = SupervisorGate()
    assert guard.check(job.actions[1], obs, [])[0] == "PASS"


def test_invalid_issuer_title_and_issue_id():
    variants = [({"author": {"login": "stranger"}}, "ISSUE_OWNER_NOT_AUTHORIZED"),
                ({"title": "[MINIFISH READ] hijack"}, "INVALID_ISSUE_TITLE"),
                ({"number": True}, "INVALID_ISSUE_NUMBER"),
                ({"number": "../42"}, "INVALID_ISSUE_NUMBER")]
    for change, expected in variants:
        raw = issue(); raw.update(change)
        with pytest.raises(InputContractError, match=expected):
            parse_scripted_fixture_issue(raw, owner=OWNER)


def test_json_is_strict_and_bounded():
    for body, expected in [("{", "INVALID_JSON"),
                           ('{"goal":1,"goal":2}', "DUPLICATE_JSON_KEY"),
                           ('{"a": NaN}', "INVALID_JSON_CONSTANT"),
                           ('[]', "INVALID_PAYLOAD"),
                           ('"hello"', "INVALID_PAYLOAD")]:
        raw = issue(); raw["body"] = body
        with pytest.raises(InputContractError, match=expected):
            parse_scripted_fixture_issue(raw, owner=OWNER)
    raw = issue(); raw["body"] = "x" * 4001
    with pytest.raises(InputContractError, match="INVALID_BODY_SIZE"):
        parse_scripted_fixture_issue(raw, owner=OWNER)
    raw = issue(); raw["body"] = {"mode": "scripted_fixture_v1"}
    with pytest.raises(InputContractError, match="INVALID_BODY_SIZE"):
        parse_scripted_fixture_issue(raw, owner=OWNER)


@pytest.mark.parametrize("delta,code", [
    ({"contract_version": True}, "INVALID_CONTRACT_VERSION"),
    ({"contract_version": 2}, "INVALID_CONTRACT_VERSION"),
    ({"mode": "agent"}, "MODE_ESCALATION_BLOCKED"),
    ({"mode": "read_only"}, "MODE_ESCALATION_BLOCKED"),
    ({"target": "https://example.com/"}, "TARGET_NOT_ALLOWLISTED"),
    ({"goal": ""}, "INVALID_GOAL"),
    ({"goal": "x" * 201}, "INVALID_GOAL"),
])
def test_block_unsafe_top_level(delta, code):
    p = payload(); p.update(delta); reject(p, code)


def test_extra_or_missing_field_fails_closed():
    p = payload(); p["allow_paid"] = True; reject(p, "UNEXPECTED_FIELDS")
    p = payload(); del p["target"]; reject(p, "UNEXPECTED_FIELDS")
    p = payload(); p["steps"] = p["steps"][:-1]; reject(p, "INVALID_STEPS")
    p = payload(); p["steps"] = "not list"; reject(p, "INVALID_STEPS")
    p = payload(); p["steps"].append({"type": "goto", "url": "https://outside.test"}); reject(p, "INVALID_STEPS")


@pytest.mark.parametrize("value", ["<b>evil</b>", "\"onclick=evil", "日本語", "A B", "", "x" * 33, "a@example.com", "A\nB", 1, True])
def test_display_name_rejects_html_unicode_spaces_secrets_and_nonstrings(value):
    p = payload(); p["steps"][1]["value"] = value; reject(p, "INVALID_DISPLAY_NAME")


def test_step_order_and_unlisted_action_types_fail_closed():
    p = payload(); p["steps"][0], p["steps"][1] = p["steps"][1], p["steps"][0]
    reject(p, "INVALID_STEP_FIELDS")
    p = payload(); p["steps"][2] = {"type": "press", "key": "Enter"}
    reject(p, "INVALID_STEP_FIELDS")
    p = payload(); p["steps"][2] = {"type": "click", "role": "button", "name": "応募"}
    reject(p, "INVALID_STEP_ACTION")
    p = payload(); p["steps"][0]["selector"] = "#open-profile"
    reject(p, "INVALID_STEP_FIELDS")
    p = payload(); p["steps"][3] = {"type": "done", "result": "fake save"}
    reject(p, "INVALID_STEP_FIELDS")


@dataclass
class FakeLedger:
    action_type: str
    decision: str = "PASS"


@dataclass
class FakeEvent:
    observation: dict


@dataclass
class FakeState:
    status: str
    ledger: list
    events: list


def state(name="MFTEST_001", *, outcome="COMPLETED", final=True):
    actions = [FakeLedger(x) for x in ["click", "fill", "click", "done"]]
    text = "保存完了\n" + name if final else "プロフィール編集\n" + name
    return FakeState(outcome, actions, [FakeEvent({"text_excerpt": text})])


def test_result_verification_requires_final_independent_observation():
    job = parse_scripted_fixture_issue(issue(), owner=OWNER)
    result = verify_scripted_fixture_state(state(), job)
    assert result["status"] == "PASS" and result["saved_visible"]
    assert result["runtime_io_verification"] == "NOT_MEASURED"
    assert "MFTEST_001" not in json.dumps(result, ensure_ascii=False)
    assert verify_scripted_fixture_state(state(final=False), job)["status"] == "FAIL"
    assert verify_scripted_fixture_state(state(name="OTHER"), job)["status"] == "FAIL"
    assert verify_scripted_fixture_state(state(outcome="FAILED"), job)["status"] == "FAIL"
    broken = state(); broken.ledger[1].decision = "HUMAN"
    assert verify_scripted_fixture_state(broken, job)["status"] == "FAIL"
    broken = state(); broken.ledger.pop()
    assert verify_scripted_fixture_state(broken, job)["status"] == "FAIL"
    broken = state(); broken.events=[]
    assert verify_scripted_fixture_state(broken, job)["status"] == "FAIL"


def test_broken_unicode_issue_body_rejected_with_fixed_error():
    raw = issue(); raw["body"] = "\ud800"
    with pytest.raises(InputContractError, match="INVALID_BODY_ENCODING"):
        parse_scripted_fixture_issue(raw, owner=OWNER)
