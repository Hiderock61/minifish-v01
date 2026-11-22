"""Offline tests for an approved Issue and a create-only execution right."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import subprocess
import sys
import threading

import pytest

from bridge_worker import run_job
from minifish import readonly_probe
from minifish.execution_right import ApprovedReadJob, run_approved_read_job


APPROVAL = ApprovedReadJob("approved-001", 15, "Read title", "https://example.com/")
ISSUE = {
    "number": 15,
    "title": "[MINIFISH READ] Offline test",
    "body": json.dumps({"mode": "read_only", "goal": APPROVAL.goal, "url": APPROVAL.url}),
}
SHA = "1" * 40


def create_response(request):
    return 201, {"ref": request["ref"], "object": {"type": "commit", "sha": request["sha"]}}


def unexpected(*args, **kwargs):
    # The gate sanitizes ordinary transport and runner errors.
    pytest.fail("unexpected claim or runner call")


def submit(*, issue=ISSUE, approval=APPROVAL, sha=SHA, claim=unexpected, runner=unexpected):
    return run_approved_read_job(
        issue, approval=approval, source_sha=sha, create_ref=claim, run_job=runner,
    )


@pytest.mark.parametrize("issue,approval,sha,reason", [
    (ISSUE, None, SHA, "APPROVAL_REQUIRED"),
    (ISSUE, replace(APPROVAL, job_id="Other/Path"), SHA, "INVALID_APPROVED_JOB_ID"),
    (ISSUE, replace(APPROVAL, goal="Other goal"), SHA, "APPROVAL_MISMATCH"),
    ({**ISSUE, "number": 16}, APPROVAL, SHA, "APPROVAL_MISMATCH"),
    ({**ISSUE, "number": True}, replace(APPROVAL, issue_number=1), SHA, "APPROVAL_MISMATCH"),
    ({**ISSUE, "body": '{"mode":"agent","url":"https://example.com/","goal":"Read title"}'},
     APPROVAL, SHA, "INVALID_ISSUE_CONTRACT"),
    ({**ISSUE, "body": ISSUE["body"][:-1] + ',"approved":true}'},
     APPROVAL, SHA, "INVALID_ISSUE_CONTRACT"),
    ({**ISSUE, "body": ISSUE["body"].replace("example.com", "other.example")},
     replace(APPROVAL, url="https://other.example/"), SHA, "URL_NOT_ALLOWLISTED"),
    (ISSUE, APPROVAL, "HEAD", "INVALID_SOURCE_SHA"),
])
def test_rejected_before_claim(issue, approval, sha, reason):
    result = submit(issue=issue, approval=approval, sha=sha)
    assert (result["status"], result["reason"]) == ("BLOCKED", reason)


@pytest.mark.parametrize("status,body,reason", [
    (200, {}, "CLAIM_UNCONFIRMED"),
    (403, {}, "CLAIM_UNCONFIRMED"),
    (409, {}, "CLAIM_CONFLICT_OR_REJECTED"),
    (422, {}, "CLAIM_CONFLICT_OR_REJECTED"),
    (500, {}, "CLAIM_UNCONFIRMED"),
    (201, None, "CLAIM_UNCONFIRMED"),
    (201, {"ref": "refs/tags/wrong", "object": {"type": "commit", "sha": SHA}},
     "CLAIM_UNCONFIRMED"),
    (201, {"ref": "refs/tags/minifish-method-c/claimed/approved-001",
           "object": {"type": "commit", "sha": "2" * 40}}, "CLAIM_UNCONFIRMED"),
])
def test_only_matching_created_response_can_admit(status, body, reason):
    result = submit(claim=lambda _: (status, body))
    assert (result["status"], result["reason"]) == ("BLOCKED", reason)


def test_timeout_before_confirmation_does_not_retry_or_run():
    attempts = []

    def timeout(request):
        attempts.append(request)
        raise TimeoutError

    result = submit(claim=timeout)
    assert result["reason"] == "CLAIM_UNCONFIRMED"
    assert len(attempts) == 1


def test_real_bridge_routes_only_after_claim(monkeypatch):
    calls = []

    def claim(request):
        calls.append(("claim", request))
        return create_response(request)

    def probe(**kwargs):
        calls.append(("probe", kwargs["job_id"], kwargs["goal"], kwargs["url"]))
        return {"status": "PASS", "run_id": "offline"}

    monkeypatch.setattr(readonly_probe, "run_public_readonly", probe)
    result = submit(claim=claim, runner=run_job)
    assert calls == [
        ("claim", {"ref": "refs/tags/minifish-method-c/claimed/approved-001", "sha": SHA}),
        ("probe", "issue_15", APPROVAL.goal, APPROVAL.url),
    ]
    assert (result["status"], result["run_id"], result["approved_job_id"]) == (
        "PASS", "offline", APPROVAL.job_id,
    )


@pytest.fixture
def local_claim_store(tmp_path):
    repo = tmp_path / "claims.git"

    def git(*args, **kwargs):
        return subprocess.run(
            ["git", "--git-dir", str(repo), *args], text=True, capture_output=True, **kwargs,
        )

    git("init", "--bare", check=True)
    tree = git("mktree", input="", check=True).stdout.strip()
    sha = git("-c", "user.name=Offline", "-c", "user.email=offline@example.invalid",
              "commit-tree", tree, "-m", "Fixture", check=True).stdout.strip()
    return git, sha


def local_create_ref(git, request):
    ref, sha = request["ref"], request["sha"]
    # Each attempt is a separate Git process; Git creates only if absent.
    updated = git("update-ref", ref, sha, "0" * 40)
    return create_response(request) if updated.returncode == 0 else (409, {})


def test_parallel_attempts_and_replay_share_one_persisted_right(local_claim_store):
    git, sha = local_claim_store
    ready = threading.Barrier(8)
    ran = []

    def claim(request):
        ready.wait(timeout=10)
        return local_create_ref(git, request)

    def execute(payload):
        ran.append(payload["number"])
        return {"status": "PASS"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: submit(sha=sha, claim=claim, runner=execute), range(8)))
    assert ran == [15]
    assert sorted(r["status"] for r in results) == ["BLOCKED"] * 7 + ["PASS"]
    # A separate Issue carrying the same approved logical ID uses the same ref.
    replay = submit(issue={**ISSUE, "number": 16}, approval=replace(APPROVAL, issue_number=16),
                    sha=sha, claim=lambda request: local_create_ref(git, request))
    assert replay["reason"] == "CLAIM_CONFLICT_OR_REJECTED"
    assert git("rev-parse", replay["claim_ref"], check=True).stdout.strip() == sha


@pytest.mark.parametrize("failure", ["response_lost", "runner_exception", "runner_fail_result"])
def test_claim_survives_uncertain_response_and_runner_failure(local_claim_store, failure):
    git, sha = local_claim_store

    def claim(request):
        created = local_create_ref(git, request)
        assert created[0] == 201
        if failure == "response_lost":
            raise TimeoutError("fixture response lost after creation")
        return created

    def execute(_):
        if failure == "runner_exception":
            raise RuntimeError("fixture runner failure")
        return {"status": "FAIL", "reason": "OFFLINE_RUNNER_FAILURE"}

    first = submit(sha=sha, claim=claim, runner=unexpected if failure == "response_lost" else execute)
    assert first["reason"] == {
        "response_lost": "CLAIM_UNCONFIRMED",
        "runner_exception": "RUNNER_ERROR_AFTER_CLAIM",
        "runner_fail_result": "OFFLINE_RUNNER_FAILURE",
    }[failure]
    assert git("rev-parse", first["claim_ref"], check=True).stdout.strip() == sha
    retry = submit(sha=sha, claim=lambda request: local_create_ref(git, request))
    assert retry["reason"] == "CLAIM_CONFLICT_OR_REJECTED"


def test_fresh_worker_after_abrupt_exit_cannot_run_again(local_claim_store):
    git, sha = local_claim_store
    repo = git("rev-parse", "--absolute-git-dir", check=True).stdout.strip()
    worker = """
import json
import os
import subprocess
import sys
from minifish.execution_right import ApprovedReadJob, run_approved_read_job

repo, sha, issue_json, approval_json = sys.argv[1:]

def create_ref(request):
    ref = request["ref"]
    created = subprocess.run(["git", "--git-dir", repo, "update-ref", ref, sha, "0" * 40],
                             capture_output=True)
    if created.returncode:
        return 409, {}
    return 201, {"ref": ref, "object": {"type": "commit", "sha": sha}}

result = run_approved_read_job(
    json.loads(issue_json), approval=ApprovedReadJob(**json.loads(approval_json)),
    source_sha=sha, create_ref=create_ref, run_job=lambda _: os._exit(37),
)
print(result["reason"])
"""
    command = [sys.executable, "-c", worker, repo, sha, json.dumps(ISSUE),
               json.dumps(vars(APPROVAL))]
    first = subprocess.run(command, text=True, capture_output=True, timeout=15)
    assert first.returncode == 37, first.stderr
    second = subprocess.run(command, text=True, capture_output=True, timeout=15, check=True)
    assert second.stdout.strip() == "CLAIM_CONFLICT_OR_REJECTED"
