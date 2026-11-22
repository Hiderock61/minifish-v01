"""Method C admission for a single approved public READ job."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import re

from .command_tower import MiniFishCommandTower
from .issue_contract import readonly_issue_payload


@dataclass(frozen=True)
class ApprovedReadJob:
    """Trusted approval supplied by the caller, independently of the Issue."""

    job_id: str
    issue_number: int
    goal: str
    url: str


def run_approved_read_job(
    issue: dict,
    *,
    approval: ApprovedReadJob | None,
    source_sha: str,
    create_ref: Callable[[dict], tuple[int, object]],
    run_job: Callable[[dict], dict],
) -> dict:
    """Call the existing bridge only after an acknowledged create-only claim.

    The trusted caller pins source_sha and supplies a single, non-retrying
    POST /git/refs transport for the shared repository. Every attempt for a
    logical job must use the same approved ID. The ref is never released by
    this gate, including on runner failure or loss of the create response.
    """
    if approval is None:
        return {"status": "BLOCKED", "reason": "APPROVAL_REQUIRED"}
    if (not isinstance(approval.job_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", approval.job_id)):
        return {"status": "BLOCKED", "reason": "INVALID_APPROVED_JOB_ID"}

    receipt = {"approved_job_id": approval.job_id}
    try:
        payload = readonly_issue_payload(issue)
    except (AttributeError, KeyError, ValueError):
        return {**receipt, "status": "BLOCKED", "reason": "INVALID_ISSUE_CONTRACT"}

    number = payload["number"]
    body = json.loads(payload["body"])
    if (type(number) is not int or number <= 0
            or type(approval.issue_number) is not int or number != approval.issue_number
            or (body["goal"], body["url"]) != (approval.goal, approval.url)):
        return {**receipt, "status": "BLOCKED", "reason": "APPROVAL_MISMATCH"}

    decision = MiniFishCommandTower.preflight_public_readonly(
        approval.job_id, body["goal"], body["url"],
    )
    if decision.state != "PASS":
        return {**receipt, "status": "BLOCKED", "reason": decision.reason}

    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        return {**receipt, "status": "BLOCKED", "reason": "INVALID_SOURCE_SHA"}

    ref = f"refs/tags/minifish-method-c/claimed/{approval.job_id}"
    receipt["claim_ref"] = ref
    try:
        status, response = create_ref({"ref": ref, "sha": source_sha})
    except Exception:
        return {**receipt, "status": "BLOCKED", "reason": "CLAIM_UNCONFIRMED"}
    if status in (409, 422):
        return {**receipt, "status": "BLOCKED", "reason": "CLAIM_CONFLICT_OR_REJECTED"}
    if (not isinstance(status, int) or status != 201
            or not isinstance(response, dict) or response.get("ref") != ref):
        return {**receipt, "status": "BLOCKED", "reason": "CLAIM_UNCONFIRMED"}
    target = response.get("object")
    if (not isinstance(target, dict) or target.get("type") != "commit"
            or target.get("sha") != source_sha):
        return {**receipt, "status": "BLOCKED", "reason": "CLAIM_UNCONFIRMED"}

    try:
        return {**run_job(payload), **receipt}
    except Exception:
        return {**receipt, "status": "FAIL", "reason": "RUNNER_ERROR_AFTER_CLAIM"}
