"""Synthetic Actions acceptance for Method C. Never dispatches a browser."""
from dataclasses import replace
from http.client import HTTPSConnection
import json
import os
from pathlib import Path
import re
import sys
from time import time_ns

from minifish.execution_right import ApprovedReadJob, run_approved_read_job
from minifish.owner_approval import approved_job_from_review, review_message


REPOSITORY = "Hiderock61/minifish-v01"
OWNER_ID = 113356792
ENVIRONMENT = "mf2-method-c-claim-qa"
JOB = ApprovedReadJob("qa-execution-right-02", 1, "Synthetic receipt only", "https://example.com/")
SCOPE = (f"Synthetic receipt only for {JOB.job_id}; check tag update and deletion on its tag, "
         f"and simulate response loss for {JOB.job_id}-lost")
BASE_SHA = "f16a39043111d0de224e793b43ab6917780a02f9"


def api_request(method, path, data=None):
    """One attempt, fixed host and repository, with no redirect or retry."""
    connection = HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(method, f"/repos/{REPOSITORY}{path}",
                           body=None if data is None else json.dumps(data), headers={
                               "Accept": "application/vnd.github+json",
                               "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                               "Content-Type": "application/json",
                               "User-Agent": "MiniFish-Method-C-QA",
                               "X-GitHub-Api-Version": "2022-11-28",
                           })
        response = connection.getresponse()
        body = response.read(262145)
        if len(body) > 262144:
            raise ValueError("oversized GitHub response")
        return response.status, json.loads(body) if body else None
    finally:
        connection.close()


def require(condition, code):
    if not condition:
        raise SystemExit(code)


def check_claims(approval, source_sha):
    issue = {"number": JOB.issue_number, "title": "[MINIFISH READ] Synthetic QA",
             "body": json.dumps({"mode": "read_only", "goal": JOB.goal, "url": JOB.url})}
    calls = []

    def receipt(payload):
        calls.append(payload["number"])
        return {"status": "PASS"}

    def create(request):
        started = time_ns()
        status, response = api_request("POST", "/git/refs", request)
        print(f"claim_http={status} start_ns={started} finish_ns={time_ns()} ref={request['ref']}")
        return status, response

    def submit(approved, transport=create, request=issue):
        return run_approved_read_job(request, approval=approved, source_sha=source_sha,
                                     create_ref=transport, run_job=receipt)

    def unexpected(_):
        raise SystemExit("unexpected ref write before approval")

    require(submit(None, unexpected)["reason"] == "APPROVAL_REQUIRED", "approval gate failed")
    altered = {**issue, "body": issue["body"].replace(JOB.goal, "Scope changed")}
    require(submit(approval, unexpected, altered)["reason"] == "APPROVAL_MISMATCH",
            "approval scope gate failed")
    require(not calls, "unapproved job reached the receipt")
    outcome = submit(approval)
    print(f"primary_status={outcome['status']} receipt_calls={len(calls)}")
    if outcome.get("reason") == "CLAIM_CONFLICT_OR_REJECTED":
        require(not calls, "contender executed")
        verify_tag(outcome["claim_ref"], source_sha)
        return
    require(outcome["status"] == "PASS" and calls == [JOB.issue_number], "claim unconfirmed")

    # Both operations can affect only the winning synthetic fixture tag.
    tag = outcome["claim_ref"].removeprefix("refs/")
    update, _ = api_request("PATCH", f"/git/refs/{tag}", {"sha": BASE_SHA, "force": True})
    print(f"fixture_update_http={update}")
    require(update in (403, 422), "fixture tag update not denied")
    verify_tag(outcome["claim_ref"], source_sha)
    deletion, _ = api_request("DELETE", f"/git/refs/{tag}")
    print(f"fixture_delete_http={deletion}")
    require(deletion in (403, 422), "fixture tag deletion not denied")
    verify_tag(outcome["claim_ref"], source_sha)

    loss_approval = replace(approval, job_id=JOB.job_id + "-lost")

    def lose_acknowledgment(request):
        status, response = create(request)
        require(status == 201 and response["ref"] == request["ref"], "loss fixture not created")
        raise TimeoutError("fault injection after GitHub acknowledged creation")

    lost = submit(loss_approval, lose_acknowledgment)
    require(lost.get("reason") == "CLAIM_UNCONFIRMED", "lost acknowledgment admitted")
    verify_tag(lost["claim_ref"], source_sha)
    retry = submit(loss_approval)
    require(retry.get("reason") == "CLAIM_CONFLICT_OR_REJECTED", "loss fixture ran on replay")
    require(calls == [JOB.issue_number], "lost acknowledgment reached the receipt")
    print("lost_acknowledgment=blocked replay=blocked")


def verify_tag(ref, source_sha):
    status, response = api_request("GET", "/git/ref/" + ref.removeprefix("refs/"))
    require(status == 200 and response.get("ref") == ref
            and response.get("object", {}).get("sha") == source_sha, "fixture tag unverified")


def main():
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY
            and os.environ["GITHUB_EVENT_NAME"] == "push", "outside QA repository or event")
    source_sha = os.environ["GITHUB_SHA"]
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha) and source_sha != BASE_SHA,
            "invalid QA source revision")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    run_attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    require(run_id > 0 and run_attempt == 1, "only fresh QA runs are approved")
    binding = dict(repository=REPOSITORY, run_id=run_id, source_sha=source_sha, scope=SCOPE)
    if sys.argv[1:] == ["prepare"]:
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            print(f"## Scope to review\n\n{SCOPE}\n\nFixture `{JOB.job_id}` and `{JOB.job_id}-lost`"
                  f"\n\nSynthetic Issue {JOB.issue_number}: `{JOB.goal}` at `{JOB.url}`"
                  f"\n\nRevision `{source_sha}`\n\nReview comment:\n\n"
                  f"`{review_message(JOB, **binding)}`", file=summary)
        return
    require(sys.argv[1:] == ["verify"], "unknown QA command")
    status, history = api_request("GET", f"/actions/runs/{run_id}/approvals")
    approval = approved_job_from_review(
        JOB, history=history, reviewer_id=OWNER_ID, environment=ENVIRONMENT,
        run_attempt=run_attempt, **binding,
    ) if status == 200 else None
    require(approval is not None, "HOLD: owner review not verified")
    print(f"review_verified run_id={run_id} owner_id={OWNER_ID} sha={source_sha}")
    check_claims(approval, source_sha)


if __name__ == "__main__":
    main()
