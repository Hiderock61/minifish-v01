#!/usr/bin/env python3
"""MiniFish local-only owner Runtime acceptance probe.

Default is READ-ONLY. Pass --start to issue at most one owner start POST.
Never prints, persists, or sends the process-local nonce anywhere but localhost:8000.
No external sites, credentials, sessions, Chromium navigation, or login.

This is an *internal runtime test*, not a remote GitHub port-forward or
CrowdWorks Chromium visual acceptance test.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

BASE = "http://127.0.0.1:8000"
ALLOWED_PATHS = frozenset(("/", "/api/owner/diagnose", "/api/owner/start"))
FIXED = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
# Never echo arbitrary uppercase strings as fixed codes. Only approved labels.
KNOWN = frozenset((
    "STOPPED", "OFFLINE", "READY", "STARTING", "STARTING_VNC",
    "STARTING_NOVNC", "STARTING_CONTROLLER", "STARTING_CHROMIUM",
    "WAITING_FOR_HUMAN", "PARTIAL_NEEDS_INSPECTION", "DESKTOP_MISSING",
    "NOVNC_MISSING", "DESKTOP_IN_USE", "AUTH_FILE_UNSAFE", "AUTH_SETUP_FAILED",
    "FAILED_VNC", "FAILED_NOVNC", "FAILED_CONTROLLER", "FAILED_CHROMIUM",
    "LOCAL_SCREEN_UNAVAILABLE", "BOOT_BLOCKED", "BOOT_FAILED_UNCLASSIFIED",
    "BOOT_CAUSE_NOT_OBSERVED", "PRIVATE_DIRECTORY_UNSAFE", "PRIVATE_LOG_UNSAFE",
    "SCRIPT_MISSING", "CODESPACE_REQUIRED", "PRIVATE_CODESPACE_REQUIRED",
    "OWNER_START_PROOF_REQUIRED", "OWNER_CROSS_SITE_REJECTED",
    "OWNER_CROSS_ORIGIN_REJECTED", "PRIVATE_OWNER_ACCESS_REJECTED",
    "PRIVATE_OWNER_SERVER_ERROR", "PRIVATE_OWNER_CONNECTION_ERROR",
))
STARTING = frozenset(("STARTING", "STARTING_VNC", "STARTING_NOVNC", "STARTING_CONTROLLER"))
MAX_RESPONSE = 65536
# Disable environment HTTP proxies. All owner API calls are strictly localhost.
OPENER = build_opener(ProxyHandler({}))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code(value: object) -> str | None:
    """Keep *only* server-defined uppercase status identifiers, never arbitrary text."""
    return value if isinstance(value, str) and FIXED.fullmatch(value) and value in KNOWN else None


def filtered(data: object) -> dict[str, object]:
    """Explicitly whitelist safe state keys; never serialize the raw response."""
    if not isinstance(data, dict):
        return {"status": None, "can_start": None, "fixed_detail": None}
    return {
        "status": code(data.get("status")),
        "can_start": data.get("can_start") if type(data.get("can_start")) is bool else None,
        "fixed_detail": code(data.get("detail")),
    }


def emit(event: str, **details: object) -> None:
    # All callers pass only safe, non-secret fields.
    print(json.dumps({"event": event, "time_utc": now_utc(), **details}, ensure_ascii=False, sort_keys=True), flush=True)


def json_request(method: str, path: str, *, payload: dict[str, str] | None = None) -> tuple[int | None, object]:
    """Bounded localhost HTTP; discard all body fields except caller's whitelist.

    The only POST target is /api/owner/start. Never enable redirects to other
    hosts or change the fixed BASE constant.
    """
    if path not in ALLOWED_PATHS or (method, path) not in (
        ("GET", "/api/owner/diagnose"), ("POST", "/api/owner/start")
    ):
        raise ValueError("Disallowed HTTP operation")
    if method == "POST" and (not isinstance(payload, dict) or set(payload) != {"nonce"}):
        raise ValueError("Invalid POST payload")
    raw = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Cache-Control": "no-store", "Accept": "application/json"}
    if method == "POST":
        headers["Content-Type"] = "application/json"
    req = Request(BASE + path, method=method, data=raw, headers=headers)
    try:
        with OPENER.open(req, timeout=5) as response:
            http = response.status
            body = response.read(MAX_RESPONSE + 1)
    except HTTPError as err:
        http = err.code
        body = err.read(MAX_RESPONSE + 1)
    except (URLError, TimeoutError, OSError):
        return None, None
    if len(body) > MAX_RESPONSE:
        return http, None
    try:
        return http, json.loads(body)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return http, None


def http_probe(port: int, path: str) -> int | None:
    if (port, path) not in ((8000, "/"), (6081, "/vnc.html"), (8002, "/login-ready")):
        raise ValueError("Disallowed HTTP probe")
    req = Request(f"http://127.0.0.1:{port}{path}", method="GET", headers={"Cache-Control": "no-store"})
    try:
        with OPENER.open(req, timeout=4) as response:
            return response.status
    except HTTPError as err:
        return err.code
    except (URLError, TimeoutError, OSError):
        return None


def tcp_probe(port: int) -> bool:
    if port not in (5911, 6081, 8002):
        raise ValueError("Disallowed TCP probe")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (TimeoutError, OSError):
        return False


def check_ready() -> bool:
    vnc = tcp_probe(5911)
    novnc = http_probe(6081, "/vnc.html")
    controller = http_probe(8002, "/login-ready")
    emit("LOCAL_PORTS", vnc_5911_listen=vnc, novnc_6081_http=novnc, controller_8002_http=controller)
    return vnc and novnc == 200 and controller == 200


def run(start: bool, wait_seconds: int = 50, interval: int = 3) -> int:
    """Return 0 only for verified read-only gate or accepted Runtime local chain."""
    emit("RUN", mode="SINGLE_POST" if start else "READ_ONLY", owner_post_count=0)
    home = http_probe(8000, "/")
    emit("LOCAL_8000_HOME", http=home)
    if home != 200:
        emit("RESULT", verdict="FAIL_8000", owner_post_count=0)
        return 2

    http, raw = json_request("GET", "/api/owner/diagnose")
    state = filtered(raw)
    # Save nonce ONLY as a local variable. It is never emitted or persisted.
    nonce = raw.get("start_nonce") if isinstance(raw, dict) else None
    nonce_ok = isinstance(nonce, str) and 40 <= len(nonce) <= 128
    emit("GATE", http=http, **state, nonce_present=nonce_ok)
    if http != 200 or state["status"] != "STOPPED" or state["can_start"] is not True:
        emit("RESULT", verdict="HOLD_INITIAL_STATE", owner_post_count=0)
        return 2
    if not start:
        emit("RESULT", verdict="INITIAL_STATE_PASS_READ_ONLY", owner_post_count=0)
        return 0
    if not nonce_ok:
        emit("RESULT", verdict="HOLD_NONCE_MISSING", owner_post_count=0)
        return 2

    # Exactly one owner start request per invocation. Do not log nonce,
    # request body, raw response, HTTP exceptions, or complete URL tokens.
    emit("POST_ATTEMPT", owner_post_count=1)
    posted_at = now_utc()
    post_http, post_raw = json_request("POST", "/api/owner/start", payload={"nonce": nonce})
    nonce = None
    post_state = filtered(post_raw)
    emit("POST_RESPONSE", request_time_utc=posted_at, http=post_http, **post_state, owner_post_count=1)
    if post_http == 403:
        emit("RESULT", verdict="FAIL_START_AUTH", owner_post_count=1)
        return 3
    if post_http != 200:
        emit("RESULT", verdict="FAIL_START_HTTP", owner_post_count=1)
        return 3
    if post_state["status"] not in STARTING and post_state["status"] != "READY":
        emit("RESULT", verdict="FAIL_PRE_VNC", owner_post_count=1)
        return 3

    deadline = time.monotonic() + wait_seconds
    latest = post_state["status"]
    while True:
        status_http, diag_raw = json_request("GET", "/api/owner/diagnose")
        status_fields = filtered(diag_raw)
        latest = status_fields["status"]
        emit("RUNTIME", http=status_http, **status_fields, owner_post_count=1)
        if status_http != 200:
            emit("RESULT", verdict="FAIL_DIAGNOSE", owner_post_count=1)
            return 4
        if latest == "READY":
            if check_ready():
                emit("RESULT", verdict="RUNTIME_LOCAL_PASS_CHROMIUM_UNVERIFIED", owner_post_count=1)
                return 0
            emit("RESULT", verdict="FAIL_READY_PORTS", owner_post_count=1)
            return 4
        if latest not in STARTING:
            emit("RESULT", verdict="FAIL_RUNTIME_FIXED_STATE" if latest else "FAIL_RUNTIME_UNKNOWN", runtime_status=latest, owner_post_count=1)
            return 4
        if time.monotonic() >= deadline:
            emit("RESULT", verdict="HOLD_START_TIMEOUT", runtime_status=latest, owner_post_count=1)
            return 4
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true", help="Explicitly authorize exactly one local owner Runtime start POST")
    parser.add_argument("--wait-seconds", type=int, default=50, help="READY observation limit after POST (1..120)")
    args = parser.parse_args(argv)
    if not 1 <= args.wait_seconds <= 120:
        parser.error("--wait-seconds must be within 1..120")
    return run(start=args.start, wait_seconds=args.wait_seconds)


if __name__ == "__main__":
    sys.exit(main())
