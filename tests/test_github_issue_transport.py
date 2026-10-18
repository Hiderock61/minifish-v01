"""Offline regression for GitHub CLI-free MiniFish issue bridge.

All transport calls are monkeypatched. Never makes remote API requests.
"""
import json
from urllib.error import HTTPError

import pytest

import bridge_worker
from minifish import github_issue_transport as bridge


def test_missing_gh_and_no_existing_token_is_safe_stop(monkeypatch):
    monkeypatch.setattr(bridge.shutil, "which",lambda name:None)
    monkeypatch.delenv("GH_TOKEN",raising=False)
    monkeypatch.delenv("GITHUB_TOKEN",raising=False)
    assert bridge.transport_ready()=="BLOCKED_NO_GITHUB_AUTH"
    with pytest.raises(bridge.BridgeTransportError,match="BRIDGE_NO_EXISTING_GITHUB_AUTH"):
        bridge.list_jobs("Hiderock61/minifish-v01","Hiderock61")


def test_existing_token_works_without_gh(monkeypatch):
    monkeypatch.setattr(bridge.shutil, "which",lambda name:None)
    monkeypatch.setenv("GITHUB_TOKEN","FAKE_TEST_TOKEN_DO_NOT_USE")
    seen=[]
    def fake_urlopen(request, timeout=0):
        seen.append((request.get_method(),request.full_url,request.get_header("Authorization")))
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):return None
            def read(self, n):
                return json.dumps([
                    {"number":1,"title":"[MINIFISH JOB] read",
                     "body":'{"mode":"read_only"}',"user":{"login":"Hiderock61"}},
                    {"number":2,"title":"[MINIFISH JOB] stranger",
                     "body":'{"mode":"agent"}',"user":{"login":"stranger"}},
                    {"number":3,"title":"OTHER",
                     "body":"{}","user":{"login":"Hiderock61"}},
                    {"number":4,"title":"[MINIFISH JOB] pull",
                     "body":"{}","user":{"login":"Hiderock61"},
                     "pull_request":{"url":"https://example.invalid/pr"}}
                ]).encode()
        return Response()
    monkeypatch.setattr(bridge,"urlopen",fake_urlopen)
    jobs=bridge.list_jobs("Hiderock61/minifish-v01","Hiderock61")
    assert [x["number"] for x in jobs]==[1]
    assert seen[0][0]=="GET"
    assert seen[0][1].startswith("https://api.github.com/repos/Hiderock61/minifish-v01/")
    assert seen[0][2]=="Bearer FAKE_TEST_TOKEN_DO_NOT_USE"


def test_rest_comment_and_close_are_explicit_write_methods(monkeypatch):
    monkeypatch.setenv("GH_TOKEN","FAKE_TEST_TOKEN")
    monkeypatch.setattr(bridge.shutil,"which",lambda name:None)
    requests=[]
    def fake_urlopen(request,timeout=0):
        requests.append((request.get_method(),request.full_url,json.loads(request.data or b"{}")))
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):return None
            def read(self,n):return b"{}"
        return Response()
    monkeypatch.setattr(bridge,"urlopen",fake_urlopen)
    bridge.comment("Hiderock61/minifish-v01",11,"PASS")
    bridge.close("Hiderock61/minifish-v01",11)
    assert requests==[
        ("POST","https://api.github.com/repos/Hiderock61/minifish-v01/issues/11/comments",{"body":"PASS"}),
        ("PATCH","https://api.github.com/repos/Hiderock61/minifish-v01/issues/11",{"state":"closed"}),
    ]


def test_http_errors_are_redacted(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN","DO_NOT_DISPLAY_TOKEN")
    monkeypatch.setattr(bridge.shutil,"which",lambda name:None)
    def bad(request,timeout=0):
        raise HTTPError(request.full_url,401,"token=DO_NOT_DISPLAY_TOKEN",None,None)
    monkeypatch.setattr(bridge,"urlopen",bad)
    with pytest.raises(bridge.BridgeTransportError) as exc:
        bridge.list_jobs("Hiderock61/minifish-v01","Hiderock61")
    assert str(exc.value)=="BRIDGE_GITHUB_HTTP_401"
    assert "DO_NOT_DISPLAY_TOKEN" not in str(exc.value)


@pytest.mark.parametrize("repo",["../other","bad","evil?x/other","http://evil/a"])
def test_unknown_repo_shapes_fail_closed(repo, monkeypatch):
    monkeypatch.setenv("GH_TOKEN","FAKE")
    with pytest.raises(bridge.BridgeTransportError):
        bridge.list_jobs(repo,"Hiderock61")


def test_paid_bridge_mode_never_launches_without_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("MINIFISH_ALLOW_PAID_BRIDGE_AGENT",raising=False)
    with pytest.raises(ValueError,match="PAID_AGENT_DISABLED_BY_DEFAULT"):
        bridge_worker.run_job({"number":100,"body":json.dumps({
            "mode":"agent","goal":"Do not run","url":"https://example.com/"
        })})
