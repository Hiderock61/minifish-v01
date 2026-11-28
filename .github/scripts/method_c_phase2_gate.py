"""Single-run, owner-approved admission for the Phase 2 synthetic-only precheck.

This module does not run Chromium or the synthetic workload. It can print a
review-bound approval string (prepare) or verify GitHub's owner review and
create a fixed, immutable claim tag once (claim). Any uncertainty is a STOP.
"""

import hashlib
from http.client import HTTPSConnection
import json
import os
from pathlib import Path
import re
import sys

REPO = "Hiderock61/minifish-v01"
OWNER_ID = 113356792
ENVIRONMENT = "mf2-method-c-claim-qa"
WORKFLOW = ".github/workflows/minifish-phase2-precheck.yml"
REF = "refs/tags/minifish-method-c/claimed/phase2-precheck-01"
SCOPE = "ONE synthetic P1/P2/P3 precheck only; no Chromium or external web job"
SAFETY_POLICY = {
    "version": "safety-property-v0.1",
    "runner_environment": "github-hosted",
    "image_os": "ubuntu24",
    "os_id": "ubuntu",
    "os_version": "24.04",
    "p1": "Unprivileged runner, PID 1 systemd, noninteractive root probe, writable "
          "cgroup v2, loaded system.slice, absent target unit and free work areas; "
          "record image version and kernel as audit evidence",
    "p2": "Read back effective service settings and verify the sole unprivileged "
          "barrier process in its dedicated cgroup before releasing synthetic work",
    "service": {
        "Type": "exec", "User": "nobody", "Group": "nogroup",
        "Restart": "no", "RuntimeMaxSec": "30s", "TimeoutStartSec": "5s",
        "TimeoutStopSec": "3s", "KillMode": "control-group", "SendSIGKILL": "yes",
        "Delegate": "no", "ProtectControlGroups": "yes", "PrivateNetwork": "yes",
        "NoNewPrivileges": "yes", "ProtectSystem": "strict", "ProtectHome": "yes",
        "PrivateTmp": "yes", "TasksMax": "4", "UMask": "0077",
    },
    "p3": "After both surrogate deaths, observe timeout of the same systemd invocation, "
          "an empty or removed cgroup, no surviving workload identities and successful cleanup",
}


class Hold(Exception):
    pass


def require(test, message):
    if not test:
        raise Hold(message)


def fixed_context(env):
    """Use only GitHub-controlled identity + validated dispatch inputs."""
    require(env.get("GITHUB_REPOSITORY") == REPO, "repository mismatch")
    require(env.get("GITHUB_REF") == "refs/heads/main", "main required")
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "manual event required")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "rerun denied")
    require(env.get("GITHUB_ACTOR_ID") == str(OWNER_ID), "owner must start run")
    run_id = env.get("GITHUB_RUN_ID", "")
    require(bool(re.fullmatch(r"[0-9]{1,20}", run_id)) and int(run_id) > 0,
            "invalid run ID")
    source = env.get("GITHUB_SHA", "")
    workflow_sha = env.get("ACTUAL_WORKFLOW_SHA", "")
    approved_sha = env.get("APPROVED_WORKFLOW_SHA", "")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source)) and source == workflow_sha
            and source == approved_sha, "source/workflow identity mismatch")
    return {
        "repository": REPO,
        "environment": ENVIRONMENT,
        "workflow": WORKFLOW,
        "run_id": int(run_id),
        "run_attempt": 1,
        "workflow_sha": source,
        "safety_policy": SAFETY_POLICY,
        "claim_ref": REF,
        "scope": SCOPE,
    }


def approval_message(manifest):
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("ascii")
    return "MF2 APPROVE " + hashlib.sha256(canonical).hexdigest()


def check_history(history, message):
    require(isinstance(history, list), "approval history missing")
    selected = []
    for item in history:
        require(isinstance(item, dict) and isinstance(item.get("environments"), list),
                "invalid review record")
        for env in item["environments"]:
            require(isinstance(env, dict) and isinstance(env.get("name"), str),
                    "invalid approval environment")
            if env["name"] == ENVIRONMENT:
                selected.append(item)
    require(len(selected) == 1, "missing or ambiguous environment review")
    review = selected[0]
    require(review.get("state") == "approved", "not approved")
    require(isinstance(review.get("user"), dict)
            and type(review["user"].get("id")) is int
            and review["user"]["id"] == OWNER_ID, "wrong approver")
    require(review.get("comment") == message, "approval comment mismatch")


def github_request(method, endpoint, payload=None):
    """One request, GitHub only, no redirects or retries; bounded response."""
    connection = HTTPSConnection("api.github.com", timeout=10)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MiniFish-Phase2-Precheck",
    }
    try:
        connection.request(method, "/repos/" + REPO + endpoint,
                           body=None if payload is None else json.dumps(payload),
                           headers=headers)
        response = connection.getresponse()
        data = response.read(262145)
        require(len(data) <= 262144, "oversized GitHub response")
        return response.status, json.loads(data) if data else None
    finally:
        connection.close()


def check_preclaim_evidence(manifest, evidence):
    require(isinstance(evidence, dict), "missing preclaim evidence")
    policy = manifest["safety_policy"]
    require(evidence.get("approval") == approval_message(manifest)
            and evidence.get("run_id") == manifest["run_id"]
            and evidence.get("workflow_sha") == manifest["workflow_sha"],
            "preclaim evidence identity mismatch")
    require(evidence.get("capability") == "PASS"
            and evidence.get("runner_environment") == policy["runner_environment"]
            and evidence.get("image_os") == policy["image_os"]
            and evidence.get("unit_empty") is True
            and evidence.get("work_area_empty") is True,
            "preclaim capability evidence incomplete")
    for field in ("image_version", "kernel", "systemd"):
        value = evidence.get(field)
        require(isinstance(value, str) and value.strip() and value.isprintable(),
                "missing or malformed preclaim evidence: " + field)


def claim(manifest, *, out, request=github_request):
    approval = approval_message(manifest)
    status, reviews = request("GET", "/actions/runs/" + str(manifest["run_id"]) + "/approvals")
    require(status == 200, "approval history GET unavailable")
    check_history(reviews, approval)

    # Read-only P1 prerequisite check after owner approval, BEFORE any tag lookup/POST.
    # Prevent import-generated __pycache__ writes before the preclaim helper loads.
    sys.dont_write_bytecode = True
    from method_c_phase2_preclaim_p1 import PreclaimHold, verify
    try:
        evidence = verify(manifest)
    except PreclaimHold as err:
        print("PHASE2_PRECLAIM_P1_HOLD run_id=" + str(manifest["run_id"])
              + " sha=" + manifest["workflow_sha"]
              + " capability=HOLD reason=" + str(err), file=sys.stderr)
        raise Hold("preclaim P1: " + str(err)) from None
    evidence["approval"] = approval
    check_preclaim_evidence(manifest, evidence)
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    out.write("preclaim_evidence=" + encoded + "\n")
    out.flush()
    print("PHASE2_PRECLAIM_P1_PASS " + encoded, flush=True)

    ref_path = "/git/ref/" + REF.removeprefix("refs/")
    status, existing = request("GET", ref_path)
    require(status == 404, "tag exists or absence cannot be established")

    # One and only one create request. If the response is lost, read back only.
    try:
        status, result = request("POST", "/git/refs",
                                 {"ref": REF, "sha": manifest["workflow_sha"]})
    except Exception as err:
        try:
            request("GET", ref_path)
        except Exception:
            pass
        raise Hold("claim response lost; no retry; check ref READ ONLY") from err
    require(status == 201 and isinstance(result, dict)
            and result.get("ref") == REF
            and isinstance(result.get("object"), dict)
            and result["object"].get("type") == "commit"
            and result["object"].get("sha") == manifest["workflow_sha"],
            "claim not acknowledged; no retry")
    status, observed = request("GET", ref_path)
    require(status == 200 and isinstance(observed, dict)
            and observed.get("ref") == REF
            and isinstance(observed.get("object"), dict)
            and observed["object"].get("type") == "commit"
            and observed["object"].get("sha") == manifest["workflow_sha"],
            "claim readback unavailable; no retry")
    out.write("acquired=true\n")
    out.flush()


def main():
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ("prepare", "claim"), "invalid command")
        manifest = fixed_context(os.environ)
        if sys.argv[1] == "prepare":
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as out:
                print("## Single-run Phase 2 synthetic precheck review\n", file=out)
                print("Run: " + str(manifest["run_id"]) + "", file=out)
                print("SHA: " + manifest["workflow_sha"] + "", file=out)
                print("Scope: " + SCOPE + "\n", file=out)
                print("Safety policy (runner image version is audit evidence):\n\n```json", file=out)
                print(json.dumps(manifest["safety_policy"], indent=2, sort_keys=True), file=out)
                print("```\n", file=out)
                print("Approve with exact comment: " + approval_message(manifest) + "", file=out)
        else:
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="ascii") as out:
                claim(manifest, out=out)
            print("PHASE2_CLAIM_ACCEPTED run_id=" + str(manifest["run_id"]))
    except (Hold, OSError, ValueError, KeyError, TimeoutError) as err:
        print("PHASE2_CLAIM_HOLD: " + str(err), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
