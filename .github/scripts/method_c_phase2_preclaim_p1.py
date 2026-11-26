"""Fail-closed, read-only P1 prerequisites BEFORE the one-shot GitHub tag POST.

This module MUST NOT create files, services, cgroups, tags, or workers. It does
not replace the formal post-claim P1/P2/P3 gate, nor certify process STOP.
"""

import os
from pathlib import Path
import re
import subprocess


class PreclaimHold(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise PreclaimHold(reason)


def verify(manifest, *, runner_version, env=None, read_text=None, lstat=None,
           is_file=None, is_dir=None, geteuid=None, command=None):
    """Inspect the SAME claim runner without changing any runner state.

    Injected accessors allow entirely synthetic tests without real sudo/systemd.
    """
    env = os.environ if env is None else env
    read_text = (lambda p: Path(p).read_text(encoding="utf-8")) if read_text is None else read_text
    lstat = (lambda p: Path(p).lstat()) if lstat is None else lstat
    is_file = (lambda p: Path(p).is_file()) if is_file is None else is_file
    is_dir = (lambda p: Path(p).is_dir()) if is_dir is None else is_dir
    geteuid = os.geteuid if geteuid is None else geteuid

    def default_command(argv):
        return subprocess.run(argv, check=False, capture_output=True,
                              text=True, timeout=5)
    command = default_command if command is None else command

    expected = manifest["approved_image_version"]
    actual = env.get("ImageVersion")
    require(bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", expected)),
            "approved image malformed")
    require(runner_version == actual == expected, "concrete runner image mismatch")
    require(env.get("ImageOS") == "ubuntu24", "unexpected image OS")
    release = read_text("/etc/os-release")
    require(bool(re.search(r'^ID="?ubuntu"?$', release, re.M))
            and bool(re.search(r'^VERSION_ID="?24\.04"?$', release, re.M)),
            "unexpected OS release")
    require(read_text("/proc/1/comm").strip() == "systemd", "PID 1 is not systemd")
    require(geteuid() != 0, "runner unexpectedly privileged")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "not first attempt")
    require(env.get("GITHUB_RUN_ID") == str(manifest["run_id"]), "run identity mismatch")
    require(env.get("GITHUB_REPOSITORY") == manifest["repository"], "repository mismatch")
    require(env.get("ACTUAL_WORKFLOW_SHA") == manifest["workflow_sha"]
            == env.get("APPROVED_WORKFLOW_SHA"), "workflow SHA mismatch")
    runner_temp = env.get("RUNNER_TEMP") or ""
    require(runner_temp.startswith("/") and "/../" not in runner_temp + "/"
            and is_dir(runner_temp), "runner temp unavailable")

    run_id = str(manifest["run_id"])
    unit = f"mf2-p2-{run_id}-1.service"
    gate = f"/run/mf2-p2-{run_id}-1"
    evidence = str(Path(runner_temp) / "mf2-phase2-evidence")
    # lstat also sees a dangling symlink; any uninspectable path fails closed.
    def require_unoccupied(path, label):
        try:
            lstat(path)
        except FileNotFoundError:
            return
        except OSError as err:
            raise PreclaimHold(label + " cannot be inspected") from err
        raise PreclaimHold(label + " already exists")

    require_unoccupied(gate, "release work area")
    require_unoccupied(evidence, "evidence work area")

    def call(argv, reason):
        try:
            result = command(argv)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PreclaimHold(reason) from exc
        require(isinstance(result.returncode, int), reason)
        return result

    systemctl_version = call(["/usr/bin/systemctl", "--version"],
                             "systemctl version unavailable")
    require(systemctl_version.returncode == 0 and
            systemctl_version.stdout.startswith("systemd "), "systemd unavailable")
    root = call(["/usr/bin/sudo", "-n", "--", "/usr/bin/id", "-u"],
                "noninteractive sudo unavailable")
    require(root.returncode == 0 and root.stdout.strip() == "0", "sudo is not root")

    cgroot = "/sys/fs/cgroup"
    mountinfo = read_text("/proc/self/mountinfo").splitlines()
    def cgroup_mount(line):
        before, sep, after = line.partition(" - ")
        left, right = before.split(), after.split()
        return bool(sep and len(left) > 5 and len(right) >= 1
                    and left[4] == cgroot and "rw" in left[5].split(",")
                    and right[0] == "cgroup2")
    require(any(cgroup_mount(line) for line in mountinfo), "writable cgroup v2 absent")
    require(is_file(f"{cgroot}/cgroup.controllers"), "cgroup controller file absent")

    def systemd_state(target):
        argv = ["/usr/bin/sudo", "-n", "--", "/usr/bin/systemctl", "show",
                "--no-pager", "--property=LoadState", target]
        output = call(argv, "systemctl show unavailable")
        values = dict(line.split("=", 1) for line in output.stdout.splitlines()
                      if "=" in line)
        require(output.returncode == 0 or values.get("LoadState") == "not-found",
                "systemctl query failed")
        return values.get("LoadState")

    require(systemd_state("system.slice") == "loaded", "system slice unavailable")
    require(systemd_state(unit) == "not-found", "target unit already exists")

    # Evidence is logged to GitHub's immutable job log by the invoking gate.
    # No filesystem write, POST, systemctl start/stop, or process spawn of worker.
    return {"run_id": run_id, "workflow_sha": manifest["workflow_sha"],
            "approved_image": expected, "measured_image": actual,
            "systemd": systemctl_version.stdout.splitlines()[0],
            "unit_empty": True, "work_area_empty": True, "capability": "PASS"}
