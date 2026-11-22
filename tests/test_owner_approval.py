"""Offline checks for the review authority and the job admitted by it."""
from dataclasses import replace
import json

import pytest

from minifish.execution_right import ApprovedReadJob, run_approved_read_job
from minifish.owner_approval import approved_job_from_review, review_message


JOB = ApprovedReadJob("test-job", 11, "Read title", "https://example.com/")
CONTEXT = dict(repository="Hiderock61/minifish-v01", run_id=25, source_sha="1" * 40,
               scope="Synthetic public READ only")
REVIEW = {
    "state": "approved", "user": {"id": 113356792},
    "comment": review_message(JOB, **CONTEXT),
    "environments": [{"name": "qa"}],
}


def verify(history, job=JOB, attempt=1, **context):
    return approved_job_from_review(
        job, history=history, reviewer_id=113356792, environment="qa", run_attempt=attempt,
        **(CONTEXT | context),
    )


@pytest.mark.parametrize("history", [
    None, {}, [], [None],
    [{**REVIEW, "state": "rejected"}],
    [{**REVIEW, "user": {"login": "Hiderock61", "id": 1}}],
    [{**REVIEW, "user": {"id": "113356792"}}],
    [{**REVIEW, "comment": "approved"}],
    [{**REVIEW, "environments": [{"name": "other"}]}],
    [REVIEW, {**REVIEW, "state": "rejected"}],
])
def test_unverified_review_never_grants_approval(history):
    assert verify(history) is None


@pytest.mark.parametrize("changes", [
    {"repository": "Other/minifish-v01"}, {"scope": "Browser may run"},
    {"run_id": 26}, {"source_sha": "2" * 40}, {"attempt": 2},
    {"job": replace(JOB, job_id="another-job")}, {"job": replace(JOB, issue_number=12)},
    {"job": replace(JOB, url="https://docs.python.org/3/")},
    {"job": replace(JOB, goal="Read text")},
])
def test_review_cannot_be_used_for_different_manifest_or_run(changes):
    assert verify([REVIEW], **changes) is None


@pytest.mark.parametrize("history,expected_calls", [([], []), ([REVIEW], ["claim", "runner"])])
def test_review_result_feeds_the_existing_claim_gate(history, expected_calls):
    calls = []

    def claim(request):
        calls.append("claim")
        return 201, {"ref": request["ref"], "object": {"type": "commit", "sha": request["sha"]}}

    def run(_):
        calls.append("runner")
        return {"status": "PASS"}

    issue = {"number": 11, "title": "[MINIFISH READ] fixture",
             "body": json.dumps({"mode": "read_only", "goal": JOB.goal, "url": JOB.url})}
    approval = verify(history)
    result = run_approved_read_job(issue, approval=approval, source_sha=CONTEXT["source_sha"],
                                   create_ref=claim, run_job=run)
    assert calls == expected_calls
    assert result["status"] == ("PASS" if history else "BLOCKED")
