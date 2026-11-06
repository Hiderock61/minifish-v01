"""No external services or credentials used in updater tests."""
import importlib.util
import json
from pathlib import Path

import pytest

PATH=Path(__file__).resolve().parent.parent/"tools/codespace_self_update.py"
spec=importlib.util.spec_from_file_location("codespace_self_update",PATH)
up=importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)

def test_owner_codespace_guard(monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME",raising=False)
    with pytest.raises(up.Hold,match="NOT_CODESPACE"):
        up.safe()
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco-test")
    monkeypatch.setattr(up,"git",lambda *a:"https://github.com/Hiderock61/minifish-v01.git"
                       if a[:2]==("remote","get-url") else "main")
    with pytest.raises(up.Hold,match="OTHER_BRANCH"):
        up.safe()

def test_requires_six_ci_checks(monkeypatch):
    sha="a"*40
    pr={"state":"open","head":{"sha":sha,
        "ref":"codex/minifish-g1-mock-encrypted-session-20261016",
        "repo":{"full_name":"Hiderock61/minifish-v01"}}}
    runs=[{"head_sha":sha,"name":n,"status":"completed","conclusion":"success"}
           for n in up.WORKFLOWS]
    monkeypatch.setattr(up,"api",lambda path:pr if path=="/pulls/33"
                        else {"workflow_runs":runs})
    assert up.verified_head()==sha
    runs[0]["conclusion"]="failure"
    with pytest.raises(up.Hold,match="CI_NOT_GREEN"):
        up.verified_head()

def test_no_download_until_green(monkeypatch):
    calls=[]
    monkeypatch.setattr(up,"safe",lambda:None)
    monkeypatch.setattr(up,"verified_head",lambda:(_ for _ in ()).throw(up.Hold("CI_NOT_GREEN")))
    monkeypatch.setattr(up,"git",lambda *a:calls.append(a))
    with pytest.raises(up.Hold,match="CI_NOT_GREEN"):
        up.once()
    assert calls==[]

def test_clean_fast_forward_and_repair(monkeypatch):
    calls=[]
    monkeypatch.setattr(up,"safe",lambda:None)
    monkeypatch.setattr(up,"verified_head",lambda:"b"*40)
    def git(*a):
        calls.append(a)
        return "a"*40 if a==("rev-parse","HEAD") else ("b"*40 if a==("rev-parse","FETCH_HEAD") else "")
    monkeypatch.setattr(up,"git",git)
    monkeypatch.setattr(up.subprocess,"run",lambda *a,**kw:type("Result",(),{"returncode":0})())
    monkeypatch.setattr(up,"refresh",lambda:calls.append(("refresh",)))
    assert up.once()=="READY_UPDATED"
    assert ("merge","--ff-only","FETCH_HEAD") in calls
    assert ("refresh",) in calls

def test_dirty_private_active_guards(monkeypatch,tmp_path):
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco")
    monkeypatch.setattr(up,"git",lambda *a:("https://github.com/Hiderock61/minifish-v01.git"
       if a[:2]==("remote","get-url") else
       "minifish-login-33" if a[0]=="symbolic-ref" else
       " M file.py" if a[0]=="status" else ""))
    with pytest.raises(up.Hold,match="DIRTY_WORKTREE"):
        up.safe()
    monkeypatch.setattr(up,"git",lambda *a:("https://github.com/Hiderock61/minifish-v01.git"
       if a[:2]==("remote","get-url") else
       "minifish-login-33" if a[0]=="symbolic-ref" else ""))
    monkeypatch.setattr(up,"ROOT",tmp_path)
    (tmp_path/".devcontainer").mkdir()
    f=tmp_path/".devcontainer/devcontainer.json"
    f.write_text(json.dumps({"portsAttributes":{str(p):{"visibility":"private"}
                                          for p in (8000,8002,6081)}}))
    monkeypatch.setattr(up,"listening",lambda port:port==8002)
    monkeypatch.setattr(up,"local",lambda port,path:{"busy":True})
    with pytest.raises(up.Hold,match="LOGIN_ACTIVE_OR_UNKNOWN"):
        up.safe()
    obj=json.loads(f.read_text())
    obj["portsAttributes"]["6081"]["visibility"]="public"
    f.write_text(json.dumps(obj))
    with pytest.raises(up.Hold,match="PORTS_NOT_PRIVATE"):
        up.safe()

def test_only_one_codespace_watcher_and_private_maintenance():
    src=(PATH.parent.parent/"start_all.sh").read_text()
    assert 'CODESPACE_NAME' in src and '--watch' in src
    assert "codespace create" not in src
    from fastapi.testclient import TestClient
    import cloud_api
    client=TestClient(cloud_api.app)
    with cloud_api.RUNS_LOCK:
        saved=dict(cloud_api.RUNS)
        cloud_api.RUNS.clear()
    try:
        assert client.get("/api/_maintenance_state").json()=={"idle":True}
        with cloud_api.RUNS_LOCK:
            cloud_api.RUNS["x"]={"status":"RUNNING"}
        assert client.get("/api/_maintenance_state").json()=={"idle":False}
    finally:
        with cloud_api.RUNS_LOCK:
            cloud_api.RUNS.clear()
            cloud_api.RUNS.update(saved)
