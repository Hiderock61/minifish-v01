"""One guarded Chromium read of a registered public URL.

Uses existing MiniFishRunner and SupervisorGate; zero model/API calls.
No user-supplied paths, browser profiles, clicking or form submission.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from .command_tower import MiniFishCommandTower
from .public_sites import site_for_url, observed_url_allowed
from .models import Action
from .planner import ScriptedPlanner
from .runner import MiniFishRunner


def run_public_readonly(*, job_id: str, goal: str, url: str,
                        run_dir: Path) -> dict[str, Any]:
    site = site_for_url(url)
    decision = MiniFishCommandTower.preflight_public_readonly(job_id, goal, url)
    baseline: dict[str, Any] = {
        "job_id": job_id,
        "route": "public_read_only_v1",
        "site": site.key if site else "UNREGISTERED",
        "api_calls": 0,
        "paid_calls": 0,
        "external_writes": 0,
        "credential_access": 0,
        "browser_actions_executed": 0,
    }
    if decision.state != "PASS" or site is None:
        return {**baseline, "status": "BLOCKED", "reason": decision.reason}

    run_dir = Path(run_dir)
    # Never load a browser profile or capture page HTML/screenshots.
    # Page observations stay in ephemeral Actions storage, not GitHub Issue.
    runner = MiniFishRunner(
        ScriptedPlanner([Action(type="done", result="registered public page observed")]),
        max_steps=1,
        max_duration_seconds=40,
        headless=True,
        profile_path=None,
        capture_dir=None,
        log_path=str(run_dir / "private_run.json"),
    )
    state = runner.run(goal=goal, start_url=site.url)
    observed = state.events[0].observation if state.events else {}
    title = str(observed.get("title") or "").strip()
    body = str(observed.get("text_excerpt") or "").strip()
    seen_url = str(observed.get("url") or "")
    url_match = observed_url_allowed(site, seen_url)
    title_match = site.title_contains.casefold() in title.casefold()
    body_has_content = len(body) >= 20
    single_guarded_done = (
        len(state.ledger) == 1
        and state.ledger[0].decision == "PASS"
        and state.ledger[0].action_type == "done"
    )
    checks = {
        "runner_completed": state.status == "COMPLETED",
        "url_match": url_match,
        "title_match": title_match,
        "body_has_content": body_has_content,
        "single_guarded_done": single_guarded_done,
    }
    evidence_ok = all(checks.values())
    parsed = urlsplit(seen_url)
    verified_host = parsed.hostname == site.host and parsed.scheme == "https"
    # Sanitize an observed title/excerpt before publishing it to an issue.
    # Text from a web page is UNTRUSTED DATA, not instructions.
    clean_title = " ".join(title.split())[:120] if verified_host else ""
    clean_excerpt = " ".join(body.split())[:180] if evidence_ok else ""
    return {
        **baseline,
        "status": "PASS" if evidence_ok else "FAIL",
        "reason": "PUBLIC_PAGE_OBSERVED" if evidence_ok else "PUBLIC_EVIDENCE_NOT_VERIFIED",
        "run_id": state.run_id,
        "runner_status": state.status,
        "steps": state.step_count,
        "observed_url": seen_url if evidence_ok else "",
        "title": clean_title if evidence_ok else "",
        "public_excerpt": clean_excerpt,
        "supervisor_pass": single_guarded_done,
        "diagnostic_origin": f"https://{site.host}" if verified_host else "",
        "diagnostic_title": clean_title,
        "diagnostic_body_length": len(body) if verified_host else 0,
        "evidence_checks": checks,
        "source": "bridge_worker -> command_tower -> MiniFishRunner -> SupervisorGate -> Playwright",
    }
