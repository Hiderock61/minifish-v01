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


@pytest.mark.parametrize("remote,expected", [
    ("OPENING_PRIVATE_BROWSER", "STARTING_CHROMIUM"),
    ("WAITING_FOR_HUMAN", "WAITING_FOR_HUMAN"),
    ("BLOCKED_PRIVATE_BROWSER", "FAILED_CHROMIUM"),
    ("BLOCKED_LOGIN_PAGE", "FAILED_CHROMIUM"),
    ("LOGIN_NOT_STARTED", None),
])
def test_chromium_phase_does_not_expose_action_nonce(monkeypatch, remote, expected):
    class SafeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, count): 
            assert count <= 4000
            return ('{"status":"' + remote + '","action_nonce":"PRIVATE_NEVER_RETURN"}').encode()
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:8002/g1/owner/status"
        assert timeout <= 1
        return SafeResponse()
    monkeypatch.setattr(owner_runtime, "urlopen", fake_urlopen)
    assert owner_runtime._handoff_phase() == expected


@pytest.mark.parametrize("marker,expected", [
    ("G1B_START_FAILED_VNC", "FAILED_VNC"),
    ("G1B_START_FAILED_NOVNC", "FAILED_NOVNC"),
    ("G1B_START_FAILED_CONTROLLER", "FAILED_CONTROLLER"),
])
def test_failure_injection_maps_fixed_code_without_secret(monkeypatch, tmp_path, marker, expected):
    monkeypatch.setenv("HOME", str(tmp_path))
    logdir = tmp_path / ".local/share/minifish"
    logdir.mkdir(parents=True, mode=0o700)
    log = logdir / "owner-desktop-boot.log"
    log.write_text("PRIVATE_DO_NOT_DISCLOSE\n" + marker + "\n")
    log.chmod(0o600)
    assert owner_runtime._known_failure() == expected
    assert "PRIVATE_DO_NOT_DISCLOSE" not in owner_runtime._known_failure()


def test_runtime_owner_reports_chromium_progress_only_after_both_ports(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESPACE_NAME", "test-codespace")
    monkeypatch.setattr(owner_runtime, "_BOOT_REQUESTED_AT", 0.0)
    script = tmp_path / "start_g1b_mock.sh"
    script.touch()
    monkeypatch.setattr(owner_runtime, "_SCRIPT", script)
    monkeypatch.setattr(owner_runtime, "_tcp_ready", lambda port: True)
    monkeypatch.setattr(owner_runtime, "_app_ready", lambda: True)
    monkeypatch.setattr(owner_runtime, "_handoff_phase", lambda: "WAITING_FOR_HUMAN")
    assert owner_runtime.diagnose() == {"status": "WAITING_FOR_HUMAN", "can_start": False}
    monkeypatch.setattr(owner_runtime, "_handoff_phase", lambda: "FAILED_CHROMIUM")
    assert owner_runtime.diagnose() == {"status": "FAILED_CHROMIUM", "can_start": False}
    monkeypatch.setattr(owner_runtime, "_tcp_ready", lambda port: False)
    assert owner_runtime.diagnose() == {"status": "PARTIAL_NEEDS_INSPECTION", "can_start": False}


def test_early_failure_cleans_up_private_vnc_auth():
    script = (ROOT / "start_g1b_mock.sh").read_text()
    assert script.index("flock -n 9") < script.index("trap cleanup EXIT")
    assert script.index("trap cleanup EXIT") < script.index('vncpasswd -f')
    assert script.index("desktop_started=1") < script.index('write_stage STARTING_NOVNC')
    assert 'rm -f "$private_dir/vnc-password.txt" "$private_dir/vnc-passwd"' in script
    assert subprocess.run(["bash", "-n", str(ROOT / "start_g1b_mock.sh")]).returncode == 0


def test_simultaneous_owner_clicks_spawn_only_one_browser_runtime(monkeypatch, tmp_path):
    from threading import Barrier, Thread
    monkeypatch.setenv("CODESPACE_NAME", "test-codespace")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(owner_runtime, "_BOOT_REQUESTED_AT", 0.0)
    script = tmp_path / "start_g1b_mock.sh"
    script.touch()
    monkeypatch.setattr(owner_runtime, "_SCRIPT", script)
    monkeypatch.setattr(owner_runtime, "_active_stage", lambda: None)
    monkeypatch.setattr(owner_runtime, "_app_ready", lambda: False)
    monkeypatch.setattr(owner_runtime, "_tcp_ready", lambda port: False)
    monkeypatch.setattr(owner_runtime, "_desktop_dependencies_present", lambda: True)
    launched = []
    monkeypatch.setattr(owner_runtime.subprocess, "Popen",
                        lambda *a, **k: launched.append((a,k)) or object())
    barrier = Barrier(3)
    results = []
    def click():
        barrier.wait()
        results.append(owner_runtime.start_owner_desktop())
    workers = [Thread(target=click) for _ in range(2)]
    for thread in workers: thread.start()
    barrier.wait()
    for thread in workers: thread.join(timeout=3)
    assert all(not thread.is_alive() for thread in workers)
    assert len(launched) == 1
    assert [r["status"] for r in results] == ["STARTING", "STARTING"]
