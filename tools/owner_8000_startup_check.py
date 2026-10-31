#!/usr/bin/env python3
"""Read-only, local Codespace startup diagnostics for MiniFish port 8000.

No service startup, process termination, code edits, owner Runtime POST, or
external requests. It does not output raw process arguments, logs, response
bodies, nonce, cookies, passwords, paths from the environment, or credentials.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

EXPECTED_CODESPACE = "accursed-apparition-6q7jwqq5965h4rpq"
API_LOG = Path("/tmp/minifish-api.log")
MAX_BODY = 32768
STATUSES = frozenset({
    "STOPPED", "READY", "STARTING", "STARTING_VNC", "STARTING_NOVNC",
    "STARTING_CONTROLLER", "STARTING_CHROMIUM", "WAITING_FOR_HUMAN",
    "PARTIAL_NEEDS_INSPECTION", "DESKTOP_MISSING", "NOVNC_MISSING",
    "FAILED_VNC", "FAILED_NOVNC", "FAILED_CONTROLLER", "FAILED_CHROMIUM",
    "BOOT_BLOCKED", "BOOT_FAILED_UNCLASSIFIED", "BOOT_CAUSE_NOT_OBSERVED",
    "CODESPACE_REQUIRED", "PRIVATE_DIRECTORY_UNSAFE", "PRIVATE_LOG_UNSAFE",
})
LOG_MARKERS = (
    ("ModuleNotFoundError", "IMPORT_MODULE_MISSING"),
    ("ImportError", "IMPORT_ERROR"),
    ("Error loading ASGI app", "ASGI_IMPORT_ERROR"),
    ("Address already in use", "PORT_IN_USE"),
    ("[Errno 98]", "PORT_IN_USE"),
    ("PermissionError", "PERMISSION_ERROR"),
    ("SyntaxError", "SYNTAX_ERROR"),
    ("Application startup failed", "APP_START_FAILED"),
    ("Traceback", "TRACEBACK_OBSERVED"),
    ("ERROR", "ERROR_MARKER"),
    ("Application startup complete", "APP_START_COMPLETE"),
    ("Uvicorn running on", "UVICORN_BOUND"),
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True), flush=True)


def processes() -> dict[str, int]:
    counts = {"uvicorn_cloud_api": 0, "start_all": 0, "start_iphone": 0}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().replace(b"\0", b" ")
        except (OSError, PermissionError):
            continue
        if b"uvicorn" in argv and b"cloud_api:app" in argv:
            counts["uvicorn_cloud_api"] += 1
        if b"bash start_all.sh" in argv:
            counts["start_all"] += 1
        if b"bash start_iphone.sh" in argv:
            counts["start_iphone"] += 1
    return counts


def listening_8000() -> bool | None:
    any_readable = False
    for file in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(file).read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        any_readable = True
        for line in lines:
            cols = line.split()
            if len(cols) > 3:
                addr = cols[1].split(":")
                if len(addr) == 2 and addr[1].upper() == "1F40" and cols[3] == "0A":
                    return True
    return False if any_readable else None


def transport(exc: URLError) -> str:
    reason = getattr(exc, "reason", None)
    no = getattr(reason, "errno", None)
    if no == errno.ECONNREFUSED:
        return "CONNECTION_REFUSED"
    if no == errno.ETIMEDOUT or isinstance(reason, TimeoutError):
        return "TIMED_OUT"
    if no in (errno.EHOSTUNREACH, errno.ENETUNREACH):
        return "HOST_UNREACHABLE"
    return "TRANSPORT_UNKNOWN"


def get_local(path: str) -> dict[str, object]:
    if path not in ("/", "/api/owner/diagnose"):
        raise ValueError("Disallowed path")
    req = Request("http://127.0.0.1:8000" + path, method="GET", headers={"Cache-Control": "no-store"})
    try:
        with OPENER.open(req, timeout=3) as resp:
            status, body = resp.status, resp.read(MAX_BODY + 1) if path != "/" else b""
    except HTTPError as exc:
        status, body = exc.code, b""
    except URLError as exc:
        return {"http": None, "transport": transport(exc)}
    except (OSError, TimeoutError):
        return {"http": None, "transport": "TRANSPORT_UNKNOWN"}
    result: dict[str, object] = {"http": status, "transport": None}
    if path != "/api/owner/diagnose":
        return result
    result["runtime_status"] = None
    result["can_start"] = None
    if status != 200 or len(body) > MAX_BODY:
        return result
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeError):
        return result
    if isinstance(parsed, dict):
        value = parsed.get("status")
        result["runtime_status"] = value if isinstance(value, str) and value in STATUSES else None
        value = parsed.get("can_start")
        result["can_start"] = value if type(value) is bool else None
    # Deliberately discard start_nonce and every other response field.
    return result


def log_summary() -> dict[str, object]:
    """Only bounded fixed markers. No arbitrary log excerpts or file paths."""
    try:
        if API_LOG.is_symlink():
            return {"state": "UNSAFE_SYMLINK"}
        info = API_LOG.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            return {"state": "UNSAFE_FILE"}
        age = max(0, round(time.time() - info.st_mtime))
        with API_LOG.open("rb") as fp:
            fp.seek(max(0, info.st_size - 16384))
            tail = fp.read(16384).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return {"state": "MISSING"}
    except OSError:
        return {"state": "UNREADABLE"}
    hits = [(tail.rfind(needle), label) for needle, label in LOG_MARKERS]
    hits = [hit for hit in hits if hit[0] >= 0]
    return {"state": "READABLE", "age_seconds": age, "size_bytes": info.st_size,
            "last_known_marker": max(hits)[1] if hits else "NO_KNOWN_MARKER",
            "has_traceback": "Traceback" in tail,
            "has_import_error": any(x in tail for x in ("ModuleNotFoundError", "ImportError"))}


def verdict(samples: list[dict[str, object]], log: dict[str, object]) -> str:
    if any(s["root"]["http"] == 200 and s["diagnose"]["http"] == 200 for s in samples):
        return "HTTP_8000_RECOVERED_OR_AVAILABLE"
    last = samples[-1]
    if last["root"]["http"] is not None:
        return "HTTP_RESPONSE_OBSERVED_NOT_200_OR_DIAG_FAIL"
    if last["tcp8000_listening"] is False and last["processes"]["uvicorn_cloud_api"] == 0:
        return "UVICORN_ABSENT_NO_LISTENER"
    if last["tcp8000_listening"] is False:
        return "UVICORN_OR_STARTUP_PRESENT_NO_LISTENER"
    if last["tcp8000_listening"] is True:
        return "PORT_LISTENING_BUT_NO_HTTP_RESPONSE"
    return "HOLD_INSUFFICIENT_READ_DATA"


def run(samples: int, interval: int) -> int:
    correct = os.environ.get("CODESPACE_NAME", "") == EXPECTED_CODESPACE
    root = Path.cwd()
    repo_files = all((root / p).is_file() for p in ("start_all.sh", "start_iphone.sh", "cloud_api.py", ".devcontainer/devcontainer.json"))
    emit("GATE", expected_codespace=correct, repository_files_present=repo_files, read_only=True, owner_post_count=0)
    if not correct or not repo_files:
        emit("RESULT", verdict="HOLD_WRONG_TARGET_OR_DIRECTORY", owner_post_count=0)
        return 2
    observations = []
    for index in range(samples):
        if index:
            time.sleep(interval)
        sample = {
            "sample": index + 1,
            "elapsed_seconds": index * interval,
            "processes": processes(),
            "tcp8000_listening": listening_8000(),
            "root": get_local("/"),
            "diagnose": get_local("/api/owner/diagnose"),
        }
        observations.append(sample)
        emit("SAMPLE", **sample)
    log = log_summary()
    emit("API_LOG", **log)
    outcome = verdict(observations, log)
    emit("RESULT", verdict=outcome, owner_post_count=0)
    return 0 if outcome == "HTTP_8000_RECOVERED_OR_AVAILABLE" else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only local MiniFish port 8000 startup observation")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--interval", type=int, default=10)
    args = p.parse_args()
    if not 1 <= args.samples <= 3 or not 0 <= args.interval <= 15:
        p.error("samples must be 1..3; interval 0..15")
    return run(args.samples, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
