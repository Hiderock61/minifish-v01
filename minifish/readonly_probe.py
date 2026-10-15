"""One safe public GET observation, dispatched via existing bridge_worker.run_job.

This is NOT a generic website agent. Only example.com is allowlisted, and
ScriptedPlanner proposes DONE after the initial Playwright navigation. No
credentials, login state, API calls, clicks, fills, submissions or retries.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from .command_tower import MiniFishCommandTower
from .models import Action
from .planner import ScriptedPlanner
from .runner import MiniFishRunner


def run_public_readonly(*, job_id: str, goal: str, url: str,
                        run_dir: Path) -> dict[str, Any]:
    decision = MiniFishCommandTower.preflight_public_readonly(job_id, goal, url)
    baseline: dict[str, Any] = {
        "job_id": job_id,
        "route": "public_read_only_v1",
        "site": "https://example.com/",
        "api_calls": 0,
        "paid_calls": 0,
        "external_writes": 0,
        "credential_access": 0,
    }
    if decision.state != "PASS":
        return {**baseline, "status": "BLOCKED", "reason": decision.reason}

    run_dir = Path(run_dir)
    # No browser profile means no cookies or authenticated site storage.
    # Never capture a screenshot or full DOM into a public GitHub Issue.
    runner = MiniFishRunner(
        ScriptedPlanner([Action(type="done", result="public page observed")]),
        max_steps=1,
        max_duration_seconds=40,
        headless=True,
        profile_path=None,
        capture_dir=None,
        log_path=str(run_dir / "private_run.json"),
    )
    state = runner.run(goal=goal, start_url="https://example.com/")
    observed = state.events[0].observation if state.events else {}
    title = str(observed.get("title") or "").strip()
    body = str(observed.get("text_excerpt") or "").strip()
    seen_url = str(observed.get("url") or "")
    # A planner's DONE alone is NOT proof that the public page loaded.
    evidence_ok = (
        state.status == "COMPLETED"
        and seen_url in ("https://example.com/", "https://example.com")
        and title == "Example Domain"
        and len(body) >= 20
        and len(state.ledger) == 1
        and state.ledger[0].decision == "PASS"
        and state.ledger[0].action_type == "done"
    )
    parsed = urlsplit(seen_url)
    diagnostic_origin = (
        f"{parsed.scheme}://{parsed.hostname}"
        if parsed.scheme in ("http", "https") and parsed.hostname else ""
    )
    checks = {
        "runner_completed": state.status == "COMPLETED",
        "url_match": seen_url in ("https://example.com/", "https://example.com"),
        "title_match": title == "Example Domain",
        "body_has_content": len(body) >= 20,
        "single_guarded_done": (
            len(state.ledger) == 1
            and state.ledger[0].decision == "PASS"
            and state.ledger[0].action_type == "done"
        ),
    }
    return {
        **baseline,
        "status": "PASS" if evidence_ok else "FAIL",
        "diagnostic_origin": diagnostic_origin,
        "diagnostic_title": title[:100] if diagnostic_origin == "https://example.com" else "",
        "diagnostic_body_length": len(body) if diagnostic_origin == "https://example.com" else 0,
        "evidence_checks": checks,
        "reason": "PUBLIC_PAGE_OBSERVED" if evidence_ok else "PUBLIC_EVIDENCE_NOT_VERIFIED",
        "run_id": state.run_id,
        "runner_status": state.status,
        "steps": state.step_count,
        "observed_url": seen_url if evidence_ok else "",
        "title": title if evidence_ok else "",
        "public_excerpt": body[:160] if evidence_ok else "",
        "supervisor_pass": evidence_ok,
        "browser_actions_executed": 0,
        "source": "bridge_worker -> command_tower preflight -> MiniFishRunner -> SupervisorGate -> Playwright",
    }
