"""Fail-closed GitHub Issue input contract for the safe Actions worker."""
from __future__ import annotations

import json


def readonly_issue_payload(issue: dict) -> dict:
    title = issue.get("title", "")
    if not isinstance(title, str) or not title.startswith("[MINIFISH READ]"):
        raise ValueError("INVALID_ISSUE_TITLE")
    raw = issue.get("body", "")
    if not isinstance(raw, str) or len(raw) > 4000:
        raise ValueError("INVALID_BODY")
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("INVALID_JSON") from None
    if not isinstance(body, dict):
        raise ValueError("INVALID_PAYLOAD")
    if set(body) != {"mode", "url", "goal"}:
        raise ValueError("UNEXPECTED_FIELDS")
    if body.get("mode") != "read_only":
        raise ValueError("MODE_ESCALATION_BLOCKED")
    if not isinstance(body["goal"], str) or not isinstance(body["url"], str):
        raise ValueError("INVALID_TYPES")
    # Only the three validated fields are passed to the existing bridge worker.
    return {
        "number": issue["number"],
        "body": json.dumps(body, ensure_ascii=False),
    }
