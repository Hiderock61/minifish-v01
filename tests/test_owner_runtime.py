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
    assert owner_runtime.diagnose()=={"status":"OFFLINE","can_start":True}
    monkeypatch.setattr(owner_runtime,"_tcp_ready",lambda port: True)
    assert owner_runtime.diagnose()["status"]=="PARTIAL_NEEDS_INSPECTION"
    monkeypatch.setattr(owner_runtime,"_app_ready",lambda: True)
    assert owner_runtime.diagnose()=={"status":"READY","can_start":False}
    monkeypatch.delenv("CODESPACE_NAME")
    assert owner_runtime.diagnose()["status"]=="CODESPACE_REQUIRED"


def test_private_start_needs_codespaces_same_origin(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME","sample")
    for req in (
        _req(),
        _req(origin="https://evil.example",header="OWNER_UI"),
        _req(origin="https://sample-8000.app.github.dev"),
        _req(origin="https://sample-8000.app.github.dev",header="OWNER_UI",host="other-8000.app.github.dev"),
    ):
        with pytest.raises(HTTPException) as err:
            cloud_api._private_owner_request(req,state_change=True)
        assert err.value.status_code==403
    cloud_api._private_owner_request(_req(
        origin="https://sample-8000.app.github.dev",header="OWNER_UI"
    ),state_change=True)


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
    assert seen==[("http://127.0.0.1:8002/login-ready",
                    "sample-8002.app.github.dev")]


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
