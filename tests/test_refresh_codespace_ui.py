"""The one-time updater must not touch any unknown process or credentials."""
import os
import sys
from pathlib import Path
import signal
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import refresh_codespace_ui as updater


@pytest.mark.parametrize("argv,expected", [
    (["/usr/local/bin/uvicorn","cloud_api:app","--host","0.0.0.0","--port","8000"],True),
    (["python","-m","uvicorn","cloud_api:app","--port","8000"],True),
    (["/usr/local/bin/uvicorn","cloud_api:app","--port","8002"],False),
    (["/usr/local/bin/uvicorn","g1b_mock_app:app","--port","8000"],False),
    (["python","script.py","cloud_api:app","--port","8000"],False),
    ([],False),
])
def test_only_exact_minifish_control_process_is_match(argv,expected):
    assert updater._is_minifish_ui(argv)==expected


def test_private_port_contract_checked_from_existing_configuration():
    assert updater._check_private_ports() is True


def test_fails_outside_codespaces_without_any_action(monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME",raising=False)
    monkeypatch.setattr(updater,"_port_listening",lambda:pytest.fail("network used"))
    assert updater.refresh_ui()=="BLOCKED_NOT_IN_CODESPACES"


def test_no_touch_if_already_correct(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME","test")
    monkeypatch.setattr(updater,"_check_private_ports",lambda:True)
    monkeypatch.setattr(updater,"_correct_ui",lambda:True)
    monkeypatch.setattr(updater,"_known_ui_processes",lambda:pytest.fail("should not scan"))
    assert updater.refresh_ui()=="READY_UI_ALREADY_CURRENT"


def test_unrecognized_process_is_not_killed(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME","test")
    monkeypatch.setattr(updater,"_check_private_ports",lambda:True)
    monkeypatch.setattr(updater,"_correct_ui",lambda:False)
    monkeypatch.setattr(updater,"_known_ui_processes",lambda:[])
    monkeypatch.setattr(updater,"_port_listening",lambda:True)
    monkeypatch.setattr(updater.os,"kill",lambda *a:pytest.fail("should not kill"))
    monkeypatch.setattr(updater.subprocess,"Popen",lambda *a,**k:pytest.fail("should not run"))
    assert updater.refresh_ui()=="BLOCKED_UNKNOWN_RUNNING_SERVICE"


def test_one_old_ui_process_refreshes_without_remote_resource(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME","test")
    monkeypatch.setattr(updater,"_check_private_ports",lambda:True)
    checks=iter([False,False,True])
    monkeypatch.setattr(updater,"_correct_ui",lambda:next(checks,True))
    monkeypatch.setattr(updater,"_known_ui_processes",lambda:[123])
    monkeypatch.setattr(updater,"_port_listening",lambda:False)
    killed=[]
    monkeypatch.setattr(updater.os,"kill",lambda pid,sig:killed.append((pid,sig)))
    monkeypatch.setattr(updater.time,"sleep",lambda n:None)
    class LocalLog:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(updater,"_private_log",lambda:LocalLog())
    run=[]
    monkeypatch.setattr(updater.subprocess,"Popen",lambda args,**kwargs:run.append((args,kwargs)))
    assert updater.refresh_ui()=="READY_UI_UPDATED"
    assert killed==[(123,signal.SIGTERM)]
    assert run[0][0]==["bash","start_iphone.sh"]
    assert run[0][1]["start_new_session"] is True
    assert "shell" not in run[0][1]


def test_no_process_restarts_nothing_except_control_ui(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME","test")
    monkeypatch.setattr(updater,"_check_private_ports",lambda:True)
    checks=iter([False,True])
    monkeypatch.setattr(updater,"_correct_ui",lambda:next(checks,True))
    monkeypatch.setattr(updater,"_known_ui_processes",lambda:[])
    monkeypatch.setattr(updater,"_port_listening",lambda:False)
    monkeypatch.setattr(updater.os,"kill",lambda *a:pytest.fail("unexpected kill"))
    monkeypatch.setattr(updater.time,"sleep",lambda n:None)
    class Dummy:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(updater,"_private_log",lambda:Dummy())
    monkeypatch.setattr(updater.subprocess,"Popen",lambda args,**kwargs:None)
    assert updater.refresh_ui()=="READY_UI_UPDATED"


def test_script_has_no_codespaces_or_git_remote_side_effects():
    src=(Path(__file__).resolve().parent.parent/"tools/refresh_codespace_ui.py").read_text()
    assert "Rebuild Container" not in src
    assert "git reset" not in src
    assert "git checkout" not in src
    assert "rm -rf" not in src
    assert "cloud_api:app" in src
    assert "start_iphone.sh" in src

def test_login_updater_matches_only_exact_private_controller():
    assert updater._is_minifish_login([
        "uvicorn", "g1b_mock_app:app", "--port", "8002",
    ])
    assert not updater._is_minifish_login([
        "uvicorn", "cloud_api:app", "--port", "8000",
    ])
    assert not updater._is_minifish_login([
        "uvicorn", "g1b_mock_app:app", "--port", "8001",
    ])


def test_login_refresh_blocked_when_active_without_stopping(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", "sample")
    monkeypatch.setattr(updater, "_check_private_ports", lambda: True)
    monkeypatch.setattr(updater, "_login_controller_current", lambda: False)
    monkeypatch.setattr(updater, "_known_login_processes", lambda: [321])
    monkeypatch.setattr(updater, "_port_listening", lambda port=8000: port == 8002)
    monkeypatch.setattr(updater, "_owner_login_idle", lambda: False)
    monkeypatch.setattr(updater.os, "kill", lambda *args: pytest.fail("unexpected stop"))
    assert updater.refresh_login_controller() == "BLOCKED_LOGIN_ACTIVE_OR_UNREADABLE"


def test_login_refresh_stops_only_known_process_then_relaunches(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", "sample")
    monkeypatch.setattr(updater, "_check_private_ports", lambda: True)
    checks = iter([False, True])
    monkeypatch.setattr(updater, "_login_controller_current", lambda: next(checks, True))
    monkeypatch.setattr(updater, "_known_login_processes", lambda: [321])
    monkeypatch.setattr(updater, "_owner_login_idle", lambda: True)
    alive = {8002: True, 6081: True, 5911: True}
    monkeypatch.setattr(updater, "_port_listening", lambda port=8000: alive.get(port, False))
    stopped = []
    def stop(pid, sig):
        stopped.append((pid, sig))
        for port in alive:
            alive[port] = False
    monkeypatch.setattr(updater.os, "kill", stop)
    class DummyLog:
        def __enter__(self): return self
        def __exit__(self, *args): return None
    monkeypatch.setattr(updater, "_private_log", lambda name: DummyLog())
    launched = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *args, **kw: launched.append((args, kw)))
    # Simulate the ready noVNC listener after controlled relaunch.
    original = updater._login_controller_current
    def ready():
        value = original()
        if value:
            alive[6081] = True
        return value
    monkeypatch.setattr(updater, "_login_controller_current", ready)
    assert updater.refresh_login_controller() == "READY_LOGIN_UPDATED"
    assert stopped == [(321, signal.SIGTERM)]
    assert launched[0][0] == ["bash", "start_g1b_mock.sh"]
    assert launched[0][1]["start_new_session"] is True


def test_login_refresh_leaves_unknown_port_untouched(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", "sample")
    monkeypatch.setattr(updater, "_check_private_ports", lambda: True)
    monkeypatch.setattr(updater, "_login_controller_current", lambda: False)
    monkeypatch.setattr(updater, "_known_login_processes", lambda: [])
    monkeypatch.setattr(updater, "_port_listening", lambda port=8000: port == 8002)
    monkeypatch.setattr(updater.os, "kill", lambda *args: pytest.fail("unexpected kill"))
    assert updater.refresh_login_controller() == "BLOCKED_UNKNOWN_LOGIN_SERVICE"
