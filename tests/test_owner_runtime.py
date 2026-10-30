"""Private controller's auto-health and one-click start: no secret exposure."""
import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import cloud_api
from minifish import owner_runtime


def _req(*, origin=None, host="sample-8000.app.github.dev", header=None):
    headers=[(b"host",host.encode())]
    if origin: headers.append((b"origin",origin.encode()))
    if header: headers.append((b"x-minifish-setup",header.encode()))
    return Request({
        "type":"http", "method":"POST", "path":"/api/owner/start",
        "scheme":"https", "server":(host,443),
        "query_string":b"", "root_path":"",
        "headers":headers,
    })


def test_status_reports_listening_ports_not_declared_ports(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    script=tmp_path / "start_g1b_mock.sh"
    script.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(owner_runtime,"_SCRIPT",script)
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda: False)
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port: False)
    assert owner_runtime.diagnose()=={"status":"STOPPED","can_start":True}
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port: True)
    assert owner_runtime.diagnose()["status"]=="PARTIAL_NEEDS_INSPECTION"
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda: True)
    assert owner_runtime.diagnose()=={"status":"READY","can_start":False}
    monkeypatch.delenv("CODESPACE_NAME")
    assert owner_runtime.diagnose()["status"]=="CODESPACE_REQUIRED"


def test_private_start_rejects_missing_wrong_or_cross_origin_nonce(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    token = cloud_api._OWNER_START_NONCE
    denied = (
        (_req(), ""),
        (_req(origin="https://evil.example"), token),
        (_req(origin="https://sample-8000.app.github.dev"), "wrong"),
    )
    for req,proof in denied:
        with pytest.raises(HTTPException) as err:
            cloud_api._private_owner_request(req,state_change=True,proof=proof)
        assert err.value.status_code==403
    # Browser-generated proof survives a proxy upstream Host rewrite.
    cloud_api._private_owner_request(
        _req(origin="https://sample-8000.app.github.dev",host="localhost:8000"),
        state_change=True,proof=token,
    )
    # If the reverse proxy suppresses Origin, a valid random proof suffices.
    cloud_api._private_owner_request(
        _req(host="localhost:8000"), state_change=True,proof=token,
    )


def test_start_invoked_once_and_secret_logs_private(monkeypatch,tmp_path):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    monkeypatch.setenv("HOME",str(tmp_path))
    script=tmp_path / "start_g1b_mock.sh"
    script.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(owner_runtime,"_SCRIPT",script)
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda:False)
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port:False)
    monkeypatch.setattr(owner_runtime,"_desktop_dependencies_present",lambda:True)
    monkeypatch.setattr(owner_runtime,"_BOOT_REQUESTED_AT",0.0)
    launches=[]
    def fake_popen(args,**kwargs):
        launches.append((args,kwargs))
        return object()
    monkeypatch.setattr(owner_runtime.subprocess,"Popen",fake_popen)
    status=owner_runtime.start_owner_desktop()
    assert status["status"]=="STARTING"
    assert len(launches)==1
    assert launches[0][0]==["bash",str(script)]
    assert (tmp_path/".local/share/minifish").stat().st_mode & 0o777==0o700
    assert (tmp_path/".local/share/minifish/owner-desktop-boot.log").stat().st_mode & 0o777==0o600
    assert not any("password" in str(a).lower() for a in launches)


def test_controller_visible_state_and_no_cli_instructions():
    html=cloud_api.CONTROL_HTML
    assert 'id="ownerBoot"' in html
    assert 'id="ownerLoginLink"' in html
    assert "/api/owner/diagnose" in html
    assert "/api/owner/start" in html
    assert "setInterval(ownerCheck,3000)" in html
    assert "git fetch" not in html
    assert "Rebuild Container" not in html



def test_no_duplicate_start_during_boot(monkeypatch,tmp_path):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    monkeypatch.setenv("HOME",str(tmp_path))
    path=tmp_path/"mock.sh"
    path.write_text("#!/bin/bash\n")
    monkeypatch.setattr(owner_runtime,"_SCRIPT",path)
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda:False)
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port:False)
    monkeypatch.setattr(owner_runtime,"_desktop_dependencies_present",lambda:True)
    monkeypatch.setattr(owner_runtime,"_BOOT_REQUESTED_AT",0.0)
    runs=[]
    monkeypatch.setattr(owner_runtime.subprocess,"Popen",
                        lambda *a,**k:runs.append(1))
    assert owner_runtime.start_owner_desktop()["status"]=="STARTING"
    assert owner_runtime.start_owner_desktop()["status"]=="STARTING"
    assert len(runs)==1


def test_known_failure_codes_are_fixed_and_secret_free(monkeypatch,tmp_path):
    monkeypatch.setenv("HOME",str(tmp_path))
    d=tmp_path/".local/share/minifish"
    d.mkdir(parents=True,mode=0o700)
    log=d/"owner-desktop-boot.log"
    log.write_text("secret: dont-share-me\nG1B_BLOCKED_NOVNC_PROXY_MISSING\n")
    log.chmod(0o600)
    assert owner_runtime._known_failure()=="NOVNC_MISSING"
    assert "dont-share-me" not in owner_runtime._known_failure()
    log.chmod(0o644)
    assert owner_runtime._known_failure()=="PRIVATE_LOG_UNSAFE"


def test_reattempt_is_allowed_only_after_boot_grace(monkeypatch,tmp_path):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    script=tmp_path/"launch.sh"
    script.write_text("#!/bin/bash\n")
    monkeypatch.setattr(owner_runtime,"_SCRIPT",script)
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda:False)
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port:False)
    now=owner_runtime.time.monotonic()
    monkeypatch.setattr(owner_runtime,"_BOOT_REQUESTED_AT",now)
    assert owner_runtime.diagnose()=={"status":"STARTING","can_start":False}
    monkeypatch.setattr(owner_runtime,"_BOOT_REQUESTED_AT",now-60)
    monkeypatch.setattr(owner_runtime,"_known_failure",lambda:"NOVNC_MISSING")
    assert owner_runtime.diagnose()=={"status":"NOVNC_MISSING","can_start":True}


def test_old_portal_is_not_accepted_as_real_login(monkeypatch):
    from urllib.request import Request
    class FakeResponse:
        status=200
        headers={"content-type":"text/html"}
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def read(self,n):return b"<h1>MOCK_LOGIN_ONLY</h1>"
    seen=[]
    def fake_open(req,timeout):
        assert isinstance(req,Request)
        seen.append((req.full_url,req.get_header("Host")))
        return FakeResponse()
    monkeypatch.setenv("CODESPACE_NAME","sample")
    monkeypatch.setattr(owner_runtime,"urlopen",fake_open)
    assert not owner_runtime._app_ready()
    assert seen==[("http://127.0.0.1:8002/login-ready", None)]


def test_missing_desktop_tool_fails_closed_no_process(monkeypatch,tmp_path):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    script=tmp_path/"launch.sh"
    script.write_text("#!/bin/bash\n")
    monkeypatch.setattr(owner_runtime,"_SCRIPT",script)
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda:False)
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port:False)
    monkeypatch.setattr(owner_runtime,"_BOOT_REQUESTED_AT",0.0)
    monkeypatch.setattr(owner_runtime,"_desktop_dependencies_present",lambda:False)
    monkeypatch.setattr(owner_runtime.subprocess,"Popen",
                        lambda *a,**k:pytest.fail("should not spawn"))
    assert owner_runtime.start_owner_desktop()=={
        "status":"DESKTOP_MISSING","can_start":False,
    }



@pytest.mark.parametrize("raw,expected", [
    ("G1B_START_FAILED_VNC", "DESKTOP_START_FAILED"),
    ("G1B_START_FAILED_LOCAL_LISTENER", "LOCAL_SCREEN_UNAVAILABLE"),
    ("G1B_START_FAILED_PASSWORD", "AUTH_SETUP_FAILED"),
    ("G1B_BLOCKED_WINDOW_MANAGER_MISSING", "DESKTOP_MISSING"),
])
def test_private_log_error_codes_no_credentials(monkeypatch,tmp_path,raw,expected):
    monkeypatch.setenv("HOME",str(tmp_path))
    private=tmp_path/".local/share/minifish"
    private.mkdir(parents=True,exist_ok=True)
    log=private/"owner-desktop-boot.log"
    log.write_text("PRIVATE_CREDENTIAL=SHOULD_NOT_LEAK\n"+raw+"\n")
    log.chmod(0o600)
    assert owner_runtime._known_failure()==expected
    assert "SHOULD_NOT_LEAK" not in owner_runtime._known_failure()


def test_owner_ui_reports_transport_and_denied_differently():
    ui=cloud_api.CONTROL_HTML
    assert 'response.status===403' in ui
    assert 'PRIVATE_OWNER_ACCESS_REJECTED' in ui
    assert 'PRIVATE_OWNER_SERVER_ERROR' in ui
    assert 'PRIVATE_OWNER_CONNECTION_ERROR' in ui
    assert 'ownerLink.style.pointerEvents="none"' in ui
    assert "ログインはまだしないでください" in ui



def test_diagnose_reads_legacy_poststart_log_without_exposing_contents(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy=tmp_path/"minifish-g1b-mock.log"
    legacy.write_text("unrelated SECRET=session-abc\nG1B_START_FAILED_VNC\n")
    legacy.chmod(0o644)
    monkeypatch.setattr(owner_runtime, "_legacy_log_path", lambda:legacy)
    assert owner_runtime._known_failure()=="DESKTOP_START_FAILED"
    assert "session-abc" not in owner_runtime._known_failure()


def test_diagnostic_prefers_newer_known_private_error(monkeypatch,tmp_path):
    monkeypatch.setenv("HOME",str(tmp_path))
    private=tmp_path/".local/share/minifish"
    private.mkdir(parents=True)
    latest=private/"owner-desktop-boot.log"
    latest.write_text("G1B_BLOCKED_NOVNC_PROXY_MISSING\n")
    latest.chmod(0o600)
    legacy=tmp_path/"minifish-g1b-mock.log"
    legacy.write_text("G1B_START_FAILED_VNC\n")
    legacy.chmod(0o644)
    older=latest.stat().st_mtime-20
    os.utime(legacy, (older,older))
    monkeypatch.setattr(owner_runtime, "_legacy_log_path",lambda:legacy)
    assert owner_runtime._known_failure()=="NOVNC_MISSING"


def test_stale_startup_log_never_claimed_current(monkeypatch,tmp_path):
    monkeypatch.setenv("HOME",str(tmp_path))
    legacy=tmp_path/"minifish-g1b-mock.log"
    legacy.write_text("G1B_START_FAILED_VNC\n")
    legacy.chmod(0o644)
    import time
    old=time.time()-9000
    os.utime(legacy,(old,old))
    monkeypatch.setattr(owner_runtime, "_legacy_log_path",lambda:legacy)
    assert owner_runtime._known_failure()=="BOOT_CAUSE_NOT_OBSERVED"



def test_owner_diagnostics_allow_codespace_proxy_rewrite(monkeypatch):
    """The screenshot's GET should work even if forwarding changes Host."""
    monkeypatch.setenv("CODESPACE_NAME", "glorious-disco-example")
    for host in (
        "glorious-disco-example-8000.app.github.dev",
        "localhost:8000",
        "127.0.0.1:8000",
    ):
        cloud_api._private_owner_request(_req(host=host))


def test_codespace_proxy_write_requires_nonce_and_not_cross_site(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", "glorious-disco-example")
    url = "https://glorious-disco-example-8000.app.github.dev"
    token = cloud_api._OWNER_START_NONCE
    for host in ("localhost:8000", "127.0.0.1:8000",
                 "glorious-disco-example-8000.app.github.dev",
                 "upstream.github.internal:8000"):
        cloud_api._private_owner_request(
            _req(host=host, origin=url), state_change=True, proof=token
        )
    with pytest.raises(HTTPException):
        cloud_api._private_owner_request(
            _req(host="localhost:8000", origin="https://evil.example"),
            state_change=True, proof=token
        )
    with pytest.raises(HTTPException):
        cloud_api._private_owner_request(
            _req(host="localhost:8000", origin=url),
            state_change=True, proof="wrong"
        )
    crosssite = _req(host="localhost:8000",origin=url)
    crosssite.scope["headers"] += [(b"sec-fetch-site",b"cross-site")]
    with pytest.raises(HTTPException):
        cloud_api._private_owner_request(
            crosssite,state_change=True,proof=token
        )


def test_codespace_diagnostics_requires_runtime(monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    with pytest.raises(HTTPException) as error:
        cloud_api._private_owner_request(
            _req(host="127.0.0.1:8000")
        )
    assert error.value.status_code == 403


def test_owner_start_nonce_exchanged_only_over_private_status_api(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESPACE_NAME","sample")
    monkeypatch.setattr(cloud_api,"owner_diagnose",
                        lambda:{"status":"OFFLINE","can_start":True})
    starts=[]
    monkeypatch.setattr(cloud_api,"start_owner_desktop",
                        lambda:starts.append(1) or {"status":"STARTING","can_start":False})
    client=TestClient(cloud_api.app,base_url="https://sample-8000.app.github.dev")
    result=client.get("/api/owner/diagnose")
    assert result.status_code == 200
    token=result.json()["start_nonce"]
    assert isinstance(token,str) and len(token)>=40
    assert token not in cloud_api.CONTROL_HTML
    invalid=client.post("/api/owner/start",json={"nonce":"wrong"})
    assert invalid.status_code==422 or invalid.status_code==403
    assert starts==[]
    failed=client.post("/api/owner/start",json={"nonce":token},
                       headers={"origin":"https://evil.example"})
    assert failed.status_code==403
    assert starts==[]
    # Rewritten Host cannot veto a request that proves private-page ownership.
    success=client.post("/api/owner/start",json={"nonce":token},
                        headers={"host":"localhost:8000",
                                 "origin":"https://sample-8000.app.github.dev",
                                 "sec-fetch-site":"same-origin"})
    assert success.status_code==200
    assert success.json()["status"]=="STARTING"
    assert starts==[1]


def test_owner_start_nonce_ui_uses_json_body_without_browser_password():
    ui=cloud_api.CONTROL_HTML
    assert "JSON.stringify({nonce:ownerStartNonce})" in ui
    assert 'headers:{"Content-Type":"application/json"}' in ui
    assert "G1_OWNER_START_NONCE_20261021" in ui
    assert "secrets.token_urlsafe" not in ui
