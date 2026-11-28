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


def verify(manifest, *, env=None, read_text=None, lstat=None,
           is_file=None, is_dir=None, geteuid=None, command=None):
    """Inspect the claim runner against the approved read-only P1 conditions.

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

    policy = manifest["safety_policy"]
    runner_environment = env.get("RUNNER_ENVIRONMENT")
    require(runner_environment == policy["runner_environment"], "unexpected runner environment")
    image_os = env.get("ImageOS")
    require(image_os == policy["image_os"], "unexpected image OS")
    image_version = env.get("ImageVersion", "")
    require(image_version.strip() and image_version.isprintable(), "image version evidence missing or malformed")
    kernel = os.uname().release
    require(kernel.strip() and kernel.isprintable(), "kernel evidence missing or malformed")
    release = read_text("/etc/os-release")
    for key, expected in (("ID", policy["os_id"]), ("VERSION_ID", policy["os_version"])):
        values = re.findall(rf"^{key}=(.*)$", release, re.M)
        require(values in ([expected], [f'"{expected}"']), "unexpected OS release")
    require(read_text("/proc/1/comm").strip() == "systemd", "PID 1 is not systemd")
    require(geteuid() != 0, "runner unexpectedly privileged")
    require(env.get("GITHUB_RUN_ATTEMPT") == str(manifest["run_attempt"]), "not first attempt")
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

    return {"run_id": manifest["run_id"], "workflow_sha": manifest["workflow_sha"],
            "runner_environment": runner_environment, "image_os": image_os,
            "image_version": image_version, "kernel": kernel,
            "systemd": systemctl_version.stdout.splitlines()[0],
            "unit_empty": True, "work_area_empty": True, "capability": "PASS"}
