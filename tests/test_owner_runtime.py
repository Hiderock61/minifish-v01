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
