"""Bind a GitHub environment review to the exact job shown to its reviewer."""
from dataclasses import asdict
import hashlib
import json

from .execution_right import ApprovedReadJob


def review_message(
    job: ApprovedReadJob, *, repository: str, run_id: int, source_sha: str, scope: str,
) -> str:
    manifest = {
        "job": asdict(job), "repository": repository, "run_id": run_id,
        "source_sha": source_sha, "scope": scope,
    }
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("ascii")
    return "MF2 APPROVE " + hashlib.sha256(data).hexdigest()


def approved_job_from_review(
    job: ApprovedReadJob, *, history: object, reviewer_id: int, environment: str,
    repository: str, run_id: int, run_attempt: int, source_sha: str, scope: str,
) -> ApprovedReadJob | None:
    """Check history obtained from GitHub for this run, independently of the Issue.

    The owner ID, environment and source revision must come from trusted workflow
    configuration. GitHub's review history is run-scoped, so reruns fail closed.
    """
    if type(run_attempt) is not int or run_attempt != 1 or not isinstance(history, list):
        return None
    reviews = []
    for record in history:
        if not isinstance(record, dict) or not isinstance(record.get("environments"), list):
            return None
        for target in record["environments"]:
            if not isinstance(target, dict) or not isinstance(target.get("name"), str):
                return None
            if target["name"] == environment:
                reviews.append(record)
    if len(reviews) != 1:
        return None
    review = reviews[0]
    user = review.get("user")
    if (review.get("state") != "approved" or not isinstance(user, dict)
            or type(user.get("id")) is not int or user["id"] != reviewer_id):
        return None
    message = review_message(
        job, repository=repository, run_id=run_id, source_sha=source_sha, scope=scope,
    )
    return job if review.get("comment") == message else None
