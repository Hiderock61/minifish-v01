from pathlib import Path
import os
import pytest

from minifish.command_tower import Mission, MiniFishCommandTower


def test_preflight_only_safe_fixture():
    f = MiniFishCommandTower.preflight
    assert f(Mission(job_id="G1", goal="observe")).state == "PASS"
    assert f(Mission(job_id="G1", goal="", route="internal_demo")).state == "STOP"
    assert f(Mission(job_id="../../private", goal="demo")).reason == "INVALID_JOB_ID"
    assert f(Mission(job_id="G1", goal="demo", route="https://example.com")).state == "HUMAN"
    assert f(Mission(job_id="G1", goal="demo", action_class="purchase")).state == "HUMAN"
    assert f(Mission(job_id="G1", goal="demo", max_paid_calls=1)).state == "HUMAN"


def test_blocked_mission_has_no_io(tmp_path):
    tower = MiniFishCommandTower()
    report = tower.execute(Mission(job_id="LIVE", goal="contact GPT",
                                   route="live_api", output_root=str(tmp_path)))
    assert report["state"] == "HUMAN"
    assert report["result"] == "NOT_EXECUTED"
    assert report["api_calls"] == 0
    assert not list(Path(tmp_path).iterdir())


@pytest.mark.skipif(os.getenv("MINIFISH_BROWSER_E2E") != "1", reason="Chromium installed only in E2E workflow")
def test_safe_full_mission_and_local_duplicate(tmp_path):
    tower = MiniFishCommandTower()
    order = Mission(job_id="BONSAI_TOWER_001", goal="verify local mock",
                    output_root=str(tmp_path))
    report = tower.execute(order)
    assert report["state"] == "COMPLETE", report
    assert report["result"] == "PASS", report
    assert report["steps"] == 4
    assert report["api_calls"] == 0
    assert report["checks"] == {
        "saved_visible": True,
        "action_sequence": True,
        "supervisor_decisions_all_pass": True,
    }
    assert (tmp_path / order.job_id / "private_run.json").exists()
    assert (tmp_path / order.job_id / "public_report.json").exists()
    again = tower.execute(order)
    assert again["reason"] == "DUPLICATE_JOB_LOCAL"
