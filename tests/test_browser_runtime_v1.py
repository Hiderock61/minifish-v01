"""Browser Runtime v1: no automatic competing launcher and no stale stage."""
import os
import subprocess
from pathlib import Path

import pytest

from minifish import owner_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_only_one_code_path_owns_browser_runtime():
    start = (ROOT / "start_all.sh").read_text()
    assert "nohup bash start_g1b_mock.sh" not in start
    assert "bash start_g1b_mock.sh >/tmp/minifish-g1b-mock.log" not in start
    assert 'bash start_iphone.sh' in start
    assert 'python bridge_worker.py' in start
    # The single owner starts the same existing script (no new browser app).
    assert "subprocess.Popen(" in (ROOT / "minifish/owner_runtime.py").read_text()


def test_launcher_protects_full_startup_before_listener_check():
    script = (ROOT / "start_g1b_mock.sh").read_text()
    assert script.index('flock -n 9') < script.index('tigervncserver :11')
    assert script.index('flock -n 9') < script.index('uvicorn g1b_mock_app:app')
    assert script.index('write_stage STARTING_VNC') < script.index('tigervncserver :11')
    assert script.index('write_stage STARTING_NOVNC') < script.index('nohup "${proxies[0]}"')
    assert script.index('write_stage STARTING_CONTROLLER') < script.index('uvicorn g1b_mock_app:app')
    assert "G1B_BLOCKED_ALREADY_STARTING" in script
    assert subprocess.run(["bash", "-n", str(ROOT / "start_g1b_mock.sh")], check=False).returncode == 0
    assert subprocess.run(["bash", "-n", str(ROOT / "start_all.sh")], check=False).returncode == 0


@pytest.mark.parametrize("stage", [
    "STARTING_VNC", "STARTING_NOVNC", "STARTING_CONTROLLER",
])
def test_live_starting_stage_is_not_misreported_stopped(monkeypatch, tmp_path, stage):
    monkeypatch.setenv("CODESPACE_NAME", "test-codespace")
    monkeypatch.setattr(owner_runtime, "_BOOT_REQUESTED_AT", 0.0)
    script = tmp_path / "start_g1b_mock.sh"
    script.touch()
    monkeypatch.setattr(owner_runtime, "_SCRIPT", script)
    monkeypatch.setattr(owner_runtime, "_tcp_ready", lambda port: False)
    monkeypatch.setattr(owner_runtime, "_app_ready", lambda: False)
    p = tmp_path / "runtime.stage"
    p.write_text("123 " + stage + "\n")
    p.chmod(0o600)
    monkeypatch.setattr(owner_runtime, "_private_state_path", lambda: p)
    monkeypatch.setattr(owner_runtime, "_process_still_running", lambda pid: pid == 123)
    assert owner_runtime.diagnose() == {"status": stage, "can_start": False}
    # A second click while script is in VNC/noVNC phase never spawns.
    monkeypatch.setattr(owner_runtime.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("duplicate launcher spawned"))
    assert owner_runtime.start_owner_desktop() == {"status": stage, "can_start": False}


def test_stale_process_and_stage_after_codespace_reopen(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESPACE_NAME", "test-codespace")
    monkeypatch.setattr(owner_runtime, "_BOOT_REQUESTED_AT", 0.0)
    script = tmp_path / "start_g1b_mock.sh"
    script.touch()
    monkeypatch.setattr(owner_runtime, "_SCRIPT", script)
    monkeypatch.setattr(owner_runtime, "_tcp_ready", lambda port: False)
    monkeypatch.setattr(owner_runtime, "_app_ready", lambda: False)
    p = tmp_path / "runtime.stage"
    p.write_text("91321 STARTING_VNC\n")
    p.chmod(0o600)
    monkeypatch.setattr(owner_runtime, "_private_state_path", lambda: p)
    monkeypatch.setattr(owner_runtime, "_process_still_running", lambda pid: False)
    assert owner_runtime.diagnose() == {"status": "STOPPED", "can_start": True}
    assert owner_runtime._active_stage() is None


@pytest.mark.parametrize("bad_state", ["../etc/passwd", "123 READY", "bad STARTING_VNC", "1 STARTING_VNC"])
def test_invalid_or_dead_pid_never_claims_ready(monkeypatch, tmp_path, bad_state):
    p = tmp_path / "runtime.stage"
    p.write_text(bad_state)
    p.chmod(0o600)
    monkeypatch.setattr(owner_runtime, "_private_state_path", lambda: p)
    monkeypatch.setattr(owner_runtime, "_process_still_running", lambda pid: False)
    assert owner_runtime._active_stage() is None


def test_unsafe_status_file_is_fail_closed(monkeypatch, tmp_path):
    p = tmp_path / "runtime.stage"
    p.symlink_to(tmp_path / "target")
    monkeypatch.setattr(owner_runtime, "_private_state_path", lambda: p)
    assert owner_runtime._active_stage() == "PARTIAL_NEEDS_INSPECTION"
    p.unlink()
    p.write_text("123 STARTING_VNC\n")
    p.chmod(0o644)
    assert owner_runtime._active_stage() == "PARTIAL_NEEDS_INSPECTION"


def test_ready_requires_controller_and_screen(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESPACE_NAME", "test-codespace")
    monkeypatch.setattr(owner_runtime, "_BOOT_REQUESTED_AT", 0.0)
    script = tmp_path / "start_g1b_mock.sh"
    script.touch()
    monkeypatch.setattr(owner_runtime, "_SCRIPT", script)
    monkeypatch.setattr(owner_runtime, "_active_stage", lambda: None)
    monkeypatch.setattr(owner_runtime, "_tcp_ready", lambda port: True)
    monkeypatch.setattr(owner_runtime, "_app_ready", lambda: False)
    assert owner_runtime.diagnose()["status"] == "PARTIAL_NEEDS_INSPECTION"
    monkeypatch.setattr(owner_runtime, "_app_ready", lambda: True)
    assert owner_runtime.diagnose() == {"status": "READY", "can_start": False}
