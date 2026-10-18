"""GitHub Issue bridge transport: gh CLI or existing authenticated REST token.

No paid provider, new credential acquisition, browser automation or login.
The caller owns the allowed repository; never emit tokens or raw response
bodies in logs. REST is a fallback when gh is missing, as in the user's
existing Codespaces terminal.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 256_000
ISSUE_LIMIT = 20


class BridgeTransportError(RuntimeError):
    """Machine-readable status only. No secrets or raw remote error body."""


def _repo(repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise BridgeTransportError("BRIDGE_REPO_INVALID")
    return repo


def _token() -> str | None:
    return os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or None


def transport_ready() -> str:
    if shutil.which("gh") is not None:
        return "GH_CLI"
    if _token():
        return "GITHUB_TOKEN"
    return "BLOCKED_NO_GITHUB_AUTH"


def _request(repo: str, method: str, path: str, payload: dict | None = None):
    # API path is fully controlled by callers; no arbitrary host or URL.
    root = "https://api.github.com/repos/" + _repo(repo)
    token = _token()
    if not token:
        raise BridgeTransportError("BRIDGE_NO_EXISTING_GITHUB_TOKEN")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MiniFish-Owner-Bridge/1.0",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(root + path, method=method, headers=headers, data=body)
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BridgeTransportError("BRIDGE_RESPONSE_TOO_LARGE")
        return json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as error:
        raise BridgeTransportError("BRIDGE_GITHUB_HTTP_" + str(error.code)) from None
    except (OSError, URLError, ValueError, UnicodeError):
        raise BridgeTransportError("BRIDGE_GITHUB_CONNECTION_FAILED") from None


def _gh(*args: str) -> str:
    try:
        result = subprocess.run(
            ["gh", *args], check=True, capture_output=True, text=True,
            timeout=15,
        )
        return result.stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise BridgeTransportError("BRIDGE_GH_CLI_FAILED") from None


def list_jobs(repo: str, owner: str) -> list[dict]:
    """Only exact creator + title matching; returns stable fields."""
    _repo(repo)
    if transport_ready() == "GH_CLI":
        raw = _gh(
            "issue", "list", "--repo", repo, "--state", "open",
            "--search", "[MINIFISH JOB] in:title", "--limit", str(ISSUE_LIMIT),
            "--json", "number,title,body,author",
        )
        try:
            entries = json.loads(raw)
        except ValueError:
            raise BridgeTransportError("BRIDGE_GH_JSON_INVALID") from None
    elif transport_ready() == "GITHUB_TOKEN":
        entries = _request(repo, "GET", "?".join((
            "/issues",
            f"state=open&per_page={ISSUE_LIMIT}",
        )))
    else:
        raise BridgeTransportError("BRIDGE_NO_EXISTING_GITHUB_AUTH")
    if not isinstance(entries, list):
        raise BridgeTransportError("BRIDGE_ISSUE_RESPONSE_INVALID")
    output = []
    for item in entries:
        author = item.get("user") or item.get("author") or {}
        if (
            "pull_request" not in item
            and str(item.get("title", "")).startswith("[MINIFISH JOB]")
            and author.get("login") == owner
            and isinstance(item.get("number"), int)
            and isinstance(item.get("body", ""), (str, type(None)))
        ):
            output.append({
                "number": item["number"], "title": item["title"],
                "body": item.get("body") or "", "author": {"login": owner},
            })
    return output


def comment(repo: str, issue_number: int, message: str) -> None:
    _repo(repo)
    if not isinstance(issue_number, int) or issue_number < 1:
        raise BridgeTransportError("BRIDGE_ISSUE_ID_INVALID")
    if transport_ready() == "GH_CLI":
        _gh("issue", "comment", str(issue_number), "--repo", repo, "--body", message)
    elif transport_ready() == "GITHUB_TOKEN":
        _request(repo, "POST", f"/issues/{issue_number}/comments", {"body": message})
    else:
        raise BridgeTransportError("BRIDGE_NO_EXISTING_GITHUB_AUTH")


def close(repo: str, issue_number: int) -> None:
    _repo(repo)
    if not isinstance(issue_number, int) or issue_number < 1:
        raise BridgeTransportError("BRIDGE_ISSUE_ID_INVALID")
    if transport_ready() == "GH_CLI":
        _gh("issue", "close", str(issue_number), "--repo", repo)
    elif transport_ready() == "GITHUB_TOKEN":
        _request(repo, "PATCH", f"/issues/{issue_number}", {"state": "closed"})
    else:
        raise BridgeTransportError("BRIDGE_NO_EXISTING_GITHUB_AUTH")
