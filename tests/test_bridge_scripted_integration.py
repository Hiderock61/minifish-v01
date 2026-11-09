"""Offline Bridge integration: NO GitHub, Codespaces, browser or AI calls."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
import bridge_worker as bridge
from minifish.scripted_input_contract import InputContractError


def issue(number=401, name="MFTEST_001", **delta):
    x = {
        "number": number, "title": "[MINIFISH JOB] fixture v1",
        "author": {"login": "Hiderock61"},
        "body": json.dumps({
            "contract_version": 1,
            "mode": "scripted_fixture_v1",
            "goal": "架空プロフィールを保存する",
            "target": "internal_profile_fixture",
            "steps": [
                {"type": "click", "role": "button", "name": "プロフィール"},
                {"type": "fill", "role": "textbox", "name": "表示名", "value": name},
                {"type": "click", "role": "button", "name": "保存"},
                {"type": "done"},
            ],
        }, ensure_ascii=False)
    }
    x.update(delta)
    return x


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setenv("MINIFISH_ENABLE_SCRIPTED_FIXTURE_V1", "1")
    monkeypatch.delenv("MINIFISH_ALLOW_PAID_BRIDGE_AGENT", raising=False)
    return tmp_path


def fake_runner_factory(log, fail=False):
    class FakeRunner:
        def __init__(self, planner, **kwargs):
            log.append(("init", kwargs))
            assert kwargs["max_steps"] == 4
            assert kwargs["profile_path"] is None
            assert kwargs["session_vault"] is None
            assert kwargs["capture_dir"] is None
            assert kwargs["log_path"] is None
            self.planner = planner
        def run(self, *, goal, start_url, start_html):
            assert start_url == "about:blank"
            assert '<button id="open-profile">プロフィール</button>' in start_html
            assert "架空プロフィール" in goal
            a = []
            for _ in range(4):
                action = self.planner.next_action(goal, None, [])
                a.append(action)
            assert [x.type for x in a] == ["click", "fill", "click", "done"]
            assert a[1].value.startswith("MFTEST_")
            log.append(("run", a[1].value))
            displayed = "保存完了\n" + a[1].value if not fail else "プロフィール編集"
            return SimpleNamespace(
                status="COMPLETED" if not fail else "FAILED",
                ledger=[SimpleNamespace(action_type=x.type,decision="PASS") for x in a],
                events=[SimpleNamespace(observation={"text_excerpt":displayed})],
            )
    return FakeRunner


def test_feature_disabled_blocks_before_runner(monkeypatch, tmp_path):
    monkeypatch.delenv("MINIFISH_ENABLE_SCRIPTED_FIXTURE_V1", raising=False)
    monkeypatch.setattr(bridge,"MiniFishRunner", lambda *a,**k: pytest.fail("runner must not start"))
    with pytest.raises(ValueError, match="SCRIPTED_FIXTURE_DISABLED"):
        bridge.preflight_issue(issue())
    with pytest.raises(ValueError, match="SCRIPTED_FIXTURE_DISABLED"):
        bridge.run_job(issue())
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name",["MFTEST_001","MFTEST_002"])
def test_fixture_to_runner_to_sanitized_report(name, isolated, monkeypatch):
    calls=[]
    monkeypatch.setattr(bridge,"MiniFishRunner",fake_runner_factory(calls))
    src = issue(name=name)
    validated = bridge.preflight_issue(src)
    assert validated.display_name==name
    result = bridge.run_job(src,validated_scripted_job=validated)
    assert result["status"]=="PASS" and result["saved_visible"]
    assert result["runtime_io_verification"]=="NOT_MEASURED"
    assert not any(name in str(v) for v in result.values())
    assert [x[0] for x in calls]==["init","run"]


def test_unsaved_result_is_not_success(isolated,monkeypatch):
    calls=[]
    monkeypatch.setattr(bridge,"MiniFishRunner",fake_runner_factory(calls,fail=True))
    x=issue()
    result=bridge.run_job(x,validated_scripted_job=bridge.preflight_issue(x))
    assert result["status"]=="FAIL"
    assert not result["saved_visible"]


@pytest.mark.parametrize("tamper", [
    lambda p: p.update(mode="agent"),
    lambda p: p.update(target="https://outside.invalid/"),
    lambda p: p["steps"].append({"type":"press", "key":"Enter"}),
    lambda p: p["steps"][2].update(name="応募"),
])
def test_invalid_never_constructs_runner(isolated,monkeypatch,tamper):
    monkeypatch.setattr(bridge,"MiniFishRunner",lambda *a,**k:pytest.fail("not allowed"))
    x=issue(); p=json.loads(x["body"]);tamper(p);x["body"]=json.dumps(p,ensure_ascii=False)
    with pytest.raises((ValueError, InputContractError)):
        bridge.preflight_issue(x)


def test_author_invalid_preflight_and_no_claim(isolated):
    x=issue(author={"login":"attacker"})
    with pytest.raises(InputContractError,match="ISSUE_OWNER_NOT_AUTHORIZED"):
        bridge.preflight_issue(x)
    assert not list(isolated.iterdir())


def test_local_atomic_claim_survives_repeated_calls_and_instance_restart(isolated):
    assert bridge.claim_scripted_issue(401)
    assert not bridge.claim_scripted_issue(401)
    assert (isolated/"runs/issue_401/.scripted_fixture_v1_claimed").is_dir()
    # Fresh process would still see this marker on the SAME persistent disk.
    assert not bridge.claim_scripted_issue(401)
    assert bridge.claim_scripted_issue(402)


def test_local_claim_competing_workers_only_one_winner(isolated):
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes=list(pool.map(lambda _: bridge.claim_scripted_issue(500),range(24)))
    assert outcomes.count(True)==1 and outcomes.count(False)==23


def exercise_main(monkeypatch, items, *, allow=True, fail=False, preclaim=False):
    if not allow:
        monkeypatch.delenv("MINIFISH_ENABLE_SCRIPTED_FIXTURE_V1",raising=False)
    msgs=[]; closed=[]; runs=[]
    monkeypatch.setattr(bridge,"list_jobs", lambda: list(items))
    monkeypatch.setattr(bridge,"comment",lambda n,m:msgs.append((n,m)))
    monkeypatch.setattr(bridge,"close",lambda n:closed.append(n))
    monkeypatch.setattr(bridge.issue_transport,"transport_ready",lambda:"TEST_TRANSPORT_MOCK")
    monkeypatch.setattr(bridge,"MiniFishRunner", fake_runner_factory(runs,fail))
    class EndLoop(Exception): pass
    monkeypatch.setattr(bridge.time,"sleep", lambda _: (_ for _ in ()).throw(EndLoop()))
    with pytest.raises(EndLoop): bridge.main()
    return msgs,closed,runs


def test_bridge_main_preflight_rejects_without_accept_comment(isolated,monkeypatch):
    items=[issue(number=602, name="<script>")]
    msgs,closed,runs=exercise_main(monkeypatch,items)
    assert closed==[602] and not runs
    assert len(msgs)==1 and "BLOCKED" in msgs[0][1]
    assert "accepted" not in msgs[0][1] and "script" not in msgs[0][1]
    assert not (isolated/"runs").exists()


def test_bridge_main_disabled_no_false_accepted(isolated,monkeypatch):
    msgs,closed,runs=exercise_main(monkeypatch,[issue(number=603)],allow=False)
    assert closed==[603] and not runs
    assert len(msgs)==1 and "SCRIPTED_FIXTURE_DISABLED" in msgs[0][1]


def test_bridge_main_accepts_and_returns_safe_report(isolated,monkeypatch):
    msgs,closed,runs=exercise_main(monkeypatch,[issue(number=604)])
    assert closed==[604]
    assert len(msgs)==2 and "accepted" in msgs[0][1]
    assert "\"status\": \"PASS\"" in msgs[1][1]
    assert "MFTEST_001" not in str(msgs)
    assert len(runs)==2
    assert (isolated/"runs/issue_604/.scripted_fixture_v1_claimed").exists()


def test_bridge_main_previously_claimed_never_restarts(isolated,monkeypatch):
    bridge.claim_scripted_issue(605)
    msgs,closed,runs=exercise_main(monkeypatch,[issue(number=605)])
    assert not msgs and not closed and not runs


def test_legacy_demo_preflight_retains_mode(isolated,monkeypatch):
    x={"number":700,"title":"[MINIFISH JOB] demo", "author":{"login":"Hiderock61"},
       "body":json.dumps({"mode":"demo","goal":"demo"})}
    assert bridge.preflight_issue(x) is None


def test_legacy_owner_status_preflight_retains_mode(isolated):
    x={"number":701,"title":"[MINIFISH JOB] status", "author":{"login":"Hiderock61"},
       "body":json.dumps({"mode":"owner_status","goal":"check"})}
    assert bridge.preflight_issue(x) is None


def test_legacy_paid_agent_default_refused(isolated,monkeypatch):
    x={"number":702,"title":"[MINIFISH JOB] agent", "author":{"login":"Hiderock61"},
       "body":json.dumps({"mode":"agent","goal":"check","url":"https://example.com/"})}
    with pytest.raises(ValueError,match="PAID_AGENT_DISABLED_BY_DEFAULT"):
        bridge.preflight_issue(x)


def test_external_transport_functions_not_called_offline(isolated,monkeypatch):
    monkeypatch.setattr(bridge.issue_transport,"comment",lambda *a,**k: pytest.fail("network forbidden"))
    monkeypatch.setattr(bridge.issue_transport,"close",lambda *a,**k: pytest.fail("network forbidden"))
    monkeypatch.setattr(bridge.issue_transport,"list_jobs",lambda *a,**k: pytest.fail("network forbidden"))
    x=issue(); assert bridge.preflight_issue(x).issue_number==401
    assert bridge.claim_scripted_issue(401)


def test_duplicate_mode_json_cannot_evade_fixture_gate(isolated,monkeypatch):
    x=issue()
    # Earlier Python json.loads would select last occurrence silently.
    x["body"] = x["body"].replace('"mode": "scripted_fixture_v1"',
                                   '"mode": "scripted_fixture_v1", "mode": "demo"')
    with pytest.raises(InputContractError,match="DUPLICATE_JSON_KEY"):
        bridge.preflight_issue(x)
    msgs,closed,runs=exercise_main(monkeypatch,[x])
    assert closed==[401] and not runs
    assert len(msgs)==1 and "BLOCKED" in msgs[0][1]
    assert "accepted" not in str(msgs)


def test_legacy_demo_run_job_still_selects_original_fixed_steps(isolated, monkeypatch):
    captured=[]
    class OldRunner:
        def __init__(self,planner,**kw):
            self.planner=planner
            assert kw["max_steps"]==25
            assert kw["profile_path"] is None
        def run(self,goal,start_url,start_html):
            assert start_url=="about:blank" and "プロフィール" in start_html
            actions=[self.planner.next_action(goal,None,[]) for _ in range(4)]
            assert [(x.type,x.name) for x in actions]==[
                ("click","プロフィール"),("fill","表示名"),
                ("click","保存"),("done",None)]
            assert actions[1].value=="ヒデロック"
            captured.extend(actions)
            return SimpleNamespace(run_id="local_demo",status="COMPLETED",step_count=4,
                                   events=[],final_result="demo",error=None)
    monkeypatch.setattr(bridge,"MiniFishRunner",OldRunner)
    legacy={"number":703,"title":"[MINIFISH JOB] demo", "author":{"login":"Hiderock61"},
       "body":json.dumps({"mode":"demo","goal":"demo"})}
    result=bridge.run_job(legacy)
    assert result["status"]=="COMPLETED" and len(captured)==4


def test_legacy_readonly_job_remains_separate(isolated,monkeypatch):
    import sys
    calls=[]
    mod=SimpleNamespace(run_public_readonly=lambda **kw:calls.append(kw) or {"status":"BLOCKED"})
    monkeypatch.setitem(sys.modules,"minifish.readonly_probe",mod)
    x={"number":704,"title":"[MINIFISH JOB] read", "author":{"login":"Hiderock61"},
       "body":json.dumps({"mode":"read_only","goal":"read", "url":"https://example.com/"})}
    assert bridge.preflight_issue(x) is None
    assert bridge.run_job(x)=={"status":"BLOCKED"}
    assert calls[0]["url"]=="https://example.com/"


def test_no_claim_after_preflight_fails(isolated):
    x=issue(name="<script>")
    with pytest.raises(InputContractError):bridge.preflight_issue(x)
    assert not (isolated/"runs").exists()
