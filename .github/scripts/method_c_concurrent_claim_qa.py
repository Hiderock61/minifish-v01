"""Two-run acceptance for the protected create-only GitHub execution right."""
import ctypes
from datetime import datetime
from http.client import HTTPSConnection, HTTPResponse, IncompleteRead
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic, monotonic_ns, sleep, time_ns

from method_c_claim_qa import ENVIRONMENT, OWNER_ID, REPOSITORY, api_request, require
from minifish.execution_right import ApprovedReadJob, run_approved_read_job
from minifish.owner_approval import approved_job_from_review, review_message


BRANCHES = {"mf2-qa/claim-02-a", "mf2-qa/claim-02-b"}
WORKFLOW = ".github/workflows/minifish-method-c-claim-qa.yml"
PROBE_STEP = "Concurrent claim probe"
JOB = ApprovedReadJob("qa-concurrent-06", 1, "Concurrent synthetic receipt", "https://example.com/")
REF = f"refs/tags/minifish-method-c/claimed/{JOB.job_id}"
SCOPE = f"One concurrent POST per Run for {REF}; synthetic receipt only"
SECOND = 10**9


def checked_get(path):
    status, data = api_request("GET", path)
    require(status == 200, f"HOLD: GitHub readiness read returned HTTP {status}")
    return data


def peer_step_starts(source_sha, run_id):
    runs = checked_get(f"/actions/runs?event=push&head_sha={source_sha}&per_page=20")
    candidates = [r for r in runs["workflow_runs"]
                  if r["path"] == WORKFLOW and r["head_branch"] in BRANCHES
                  and r["head_sha"] == source_sha and r["run_attempt"] == 1]
    if len(candidates) < 2:
        return None
    require(len(candidates) == 2 and {r["head_branch"] for r in candidates} == BRANCHES
            and run_id in {r["id"] for r in candidates}, "HOLD: unexpected Run pair")
    ready = {}
    for run in candidates:
        jobs = checked_get(f"/actions/runs/{run['id']}/attempts/1/jobs")
        verify = next((job for job in jobs["jobs"] if job["name"] == "verify"), None)
        if not verify or verify["status"] != "in_progress":
            return None
        step = next((step for step in verify["steps"] if step["name"] == PROBE_STEP), None)
        if not step or step["status"] != "in_progress" or not step["started_at"]:
            return None
        ready[run["id"]] = int(datetime.fromisoformat(step["started_at"]).timestamp())
    return ready


def rendezvous(source_sha, run_id):
    deadline = monotonic() + 330
    while monotonic() < deadline:
        ready = peer_step_starts(source_sha, run_id)
        if ready:
            target = (max(ready.values()) + 35) * SECOND
            require(target - time_ns() >= 4 * SECOND, "HOLD: readiness observed too late")
            print(f"rendezvous={json.dumps(ready, sort_keys=True)} target_ns={target}", flush=True)
            return target
        sleep(3)
    raise SystemExit("HOLD: both Runs did not reach the pre-claim step")


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def seconds(output, key):
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*([+-]?\d+(?:\.\d+)?)\s*(ns|us|µs|ms|s)\b", output)
    if not match:
        return None
    scale = {"ns": 1e-9, "us": 1e-6, "µs": 1e-6, "ms": 1e-3, "s": 1}
    return abs(float(match[1])) * scale[match[2]]


def kernel_clock_evidence():
    # glibc x86_64 ntptimeval: timeval, maxerror, esterror, tai, four reserved longs.
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        return None
    try:
        sample = (ctypes.c_long * 9)()
        get_time = ctypes.CDLL("libc.so.6").ntp_gettime
        get_time.argtypes = [ctypes.c_void_p]
        state = get_time(ctypes.byref(sample))
    except (AttributeError, OSError):
        return None
    if state != 0 or not 0 <= sample[3] <= sample[2] < 500_000:
        return None
    return {"source": "linux-ntp", "maxerror_us": sample[2], "esterror_us": sample[3],
            "uncertainty_ns": sample[2] * 1000 + 20_000_000}


def clock_evidence():
    """Estimate conservative UTC uncertainty from live host sync telemetry."""
    tracking = command("chronyc", "-n", "tracking")
    if re.search(r"(?m)^Leap status\s*:\s*Normal\s*$", tracking):
        def metric(key):
            match = re.search(rf"(?m)^{re.escape(key)}\s*:\s*([+-]?\d+(?:\.\d+)?)\s+seconds", tracking)
            return abs(float(match[1])) if match else None

        offset, delay, dispersion = (metric(k) for k in ("System time", "Root delay", "Root dispersion"))
        if None not in (offset, delay, dispersion):
            return {"source": "chrony", "offset_s": offset, "root_delay_s": delay,
                    "dispersion_s": dispersion,
                    "uncertainty_ns": int((offset + delay / 2 + dispersion + .020) * SECOND)}
    if command("timedatectl", "show", "-p", "NTPSynchronized", "--value") == "yes":
        tracking = command("timedatectl", "timesync-status")
        distance, offset, delay, jitter = (seconds(tracking, k) for k in
                                           ("Root distance", "Offset", "Delay", "Jitter"))
        if None not in (distance, offset, delay, jitter):
            return {"source": "systemd-timesyncd", "distance_s": distance, "offset_s": offset,
                    "delay_s": delay, "jitter_s": jitter,
                    "uncertainty_ns": int((distance + offset + delay / 2 + jitter + .020) * SECOND)}
    return kernel_clock_evidence() or {"source": "unavailable", "uncertainty_ns": None}


def attempt_claim(approval, source_sha, target):
    connection = HTTPSConnection("api.github.com", timeout=10)
    sent = received = None
    calls = 0

    def record(event, **fields):
        print(json.dumps({"event": event, "job_id": JOB.job_id, "ref": REF, **fields}), flush=True)

    def create(request):
        nonlocal sent, received
        require(request == {"ref": REF, "sha": source_sha}, "unexpected claim")
        while (remaining := target - time_ns()) > 0:
            sleep(remaining / SECOND)
        require(time_ns() - target <= 250_000_000, "HOLD: missed common launch time")

        phase = "connect"
        started = monotonic_ns()

        class ObservedResponse(HTTPResponse):
            def _read_status(self):
                nonlocal phase, received
                phase = "status_line"
                result = super()._read_status()
                timestamp = time_ns()
                record("status_line", at_ns=timestamp, claim_http=result[1])
                if result[1] != 100:
                    received = timestamp
                phase = "headers"
                return result

        connection.response_class = ObservedResponse
        try:
            record("connect_start", at_ns=time_ns(), target_ns=target)
            connection.connect()
            record("connect_complete", at_ns=time_ns())
            phase = "send"
            record("send_start", at_ns=time_ns())
            connection.request("POST", f"/repos/{REPOSITORY}/git/refs", json.dumps(request), headers={
                "Accept": "application/vnd.github+json", "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "MiniFish-Method-C-Concurrent-QA",
            })
            sent = time_ns()
            record("send_complete", at_ns=sent)
            phase = "status_line"
            response = connection.getresponse()
            request_id = response.getheader("X-GitHub-Request-Id", "")
            record("headers_complete", at_ns=time_ns(), claim_http=response.status,
                   request_id=request_id if re.fullmatch(r"[A-Fa-f0-9:]{1,128}", request_id) else None)
            phase = "body_read"
            expected_size = response.length
            body = response.read(262145)
            if len(body) > 262144:
                raise ValueError("oversized response body")
            if expected_size is not None and len(body) < expected_size:
                raise IncompleteRead(body, expected_size - len(body))
            record("body_read_complete", at_ns=time_ns(), size_bytes=len(body))
            phase = "body_parse"
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("unexpected response shape")
            obj = data.get("object")
            object_matches = isinstance(obj, dict) and data.get("ref") == REF and obj.get("sha") == source_sha
            record("body_parse_complete", at_ns=time_ns(), object_matches=object_matches,
                   reference_already_exists=data.get("message") in ("Reference already exists", "Reference already exists."))
        except Exception as error:
            record("communication_error", at_ns=time_ns(), phase=phase, error_type=type(error).__name__,
                   elapsed_ns=monotonic_ns() - started)
            raise
        return response.status, data

    def receipt(_payload):
        nonlocal calls
        calls += 1
        return {"status": "PASS"}

    issue = {"number": JOB.issue_number, "title": "[MINIFISH READ] Synthetic concurrency QA",
             "body": json.dumps({"mode": "read_only", "goal": JOB.goal, "url": JOB.url})}
    try:
        delay = (target - time_ns()) / SECOND - 8
        if delay > 0:
            sleep(delay)
        before = clock_evidence()
        clock_start, monotonic_start = time_ns(), monotonic_ns()
        outcome = run_approved_read_job(issue, approval=approval, source_sha=source_sha,
                                        create_ref=create, run_job=receipt)
        clock_jump = abs((time_ns() - clock_start) - (monotonic_ns() - monotonic_start))
        after = clock_evidence()
    finally:
        connection.close()
    print(json.dumps({"receipt_calls": calls, "outcome": outcome, "clock_before": before,
                      "clock_after": after, "clock_jump_ns": clock_jump, "sent_ns": sent,
                      "status_line_ns": received}), flush=True)
    require(outcome["status"] == "PASS" and calls == 1 or
            outcome.get("reason") == "CLAIM_CONFLICT_OR_REJECTED" and calls == 0,
            "HOLD: claim outcome could not be confirmed")


def main():
    source_sha = os.environ["GITHUB_SHA"]
    run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY and os.environ["GITHUB_EVENT_NAME"] == "push"
            and os.environ["GITHUB_REF_NAME"] in BRANCHES and attempt == 1 and run_id > 0
            and re.fullmatch(r"[0-9a-f]{40}", source_sha), "outside concurrent QA scope")
    binding = dict(repository=REPOSITORY, run_id=run_id, source_sha=source_sha, scope=SCOPE)
    if sys.argv[1:] == ["prepare"]:
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            print(f"## Scope to review\n\n{SCOPE}\n\nRevision `{source_sha}`\n\n"
                  f"Review comment:\n\n`{review_message(JOB, **binding)}`", file=summary)
        return
    history = checked_get(f"/actions/runs/{run_id}/approvals")
    approval = approved_job_from_review(JOB, history=history, reviewer_id=OWNER_ID,
                                        environment=ENVIRONMENT, run_attempt=attempt, **binding)
    require(approval is not None, "HOLD: owner review not verified")
    print(f"review_verified run_id={run_id} owner_id={OWNER_ID} sha={source_sha}", flush=True)
    if sys.argv[1:] == ["arm"]:
        status, _ = api_request("GET", "/git/ref/" + REF.removeprefix("refs/"))
        require(status == 404, "HOLD: test tag already exists or its absence is unverified")
        return
    require(sys.argv[1:] == ["claim"], "unknown QA command")
    attempt_claim(approval, source_sha, rendezvous(source_sha, run_id))


if __name__ == "__main__":
    main()
