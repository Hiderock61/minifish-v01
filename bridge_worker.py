from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from minifish import Action, MiniFishRunner, OpenAIPlanner, ScriptedPlanner
from minifish import github_issue_transport as issue_transport
from minifish.scripted_input_contract import (
    MODE as SCRIPTED_MODE, InputContractError,
    parse_scripted_fixture_issue, verify_scripted_fixture_state,
    decode_issue_json,
)

REPO = os.getenv("MINIFISH_BRIDGE_REPO", "Hiderock61/minifish-v01")
OWNER = os.getenv("MINIFISH_BRIDGE_OWNER", "Hiderock61")
POLL_SECONDS = float(os.getenv("MINIFISH_BRIDGE_POLL_SECONDS", "5"))
RUN_ROOT = Path(os.getenv("MINIFISH_RUN_ROOT", ".minifish/runs"))
PROFILE_PATH = os.getenv("MINIFISH_PROFILE_PATH", ".minifish/profile.json")


def list_jobs() -> list[dict]:
    return issue_transport.list_jobs(REPO, OWNER)


def comment(number: int, message: str) -> None:
    issue_transport.comment(REPO, number, message)


def close(number: int) -> None:
    issue_transport.close(REPO, number)


def _scripted_enabled() -> bool:
    return os.getenv("MINIFISH_ENABLE_SCRIPTED_FIXTURE_V1") == "1"


def preflight_issue(issue: dict):
    """Fail closed BEFORE acceptance; live script mode is disabled by default."""
    raw = issue.get("body")
    if not isinstance(raw, str):
        raise ValueError("INVALID_ISSUE_BODY")
    payload = decode_issue_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("INVALID_ISSUE_PAYLOAD")
    mode = payload.get("mode", "demo")
    if mode == SCRIPTED_MODE:
        if not _scripted_enabled():
            raise ValueError("SCRIPTED_FIXTURE_DISABLED")
        return parse_scripted_fixture_issue(issue, owner=OWNER)
    goal = payload.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("GOAL_REQUIRED")
    if mode == "agent":
        if os.getenv("MINIFISH_ALLOW_PAID_BRIDGE_AGENT") != "1":
            raise ValueError("PAID_AGENT_DISABLED_BY_DEFAULT")
        url = payload.get("url", "")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError("INVALID_AGENT_START_URL")
    elif mode not in ("demo", "owner_status", "read_only"):
        raise ValueError("UNRECOGNIZED_MODE")
    return None


def claim_scripted_issue(number: int) -> bool:
    """Atomic local claim survives Bridge restart; never auto-retry ambiguous work.

    Only protects the SAME persistent RUN_ROOT filesystem, not multiple workers
    on disjoint machines or a deleted Codespace. No secret data is written.
    """
    if type(number) is not int or not 1 <= number <= 2_000_000_000:
        raise ValueError("INVALID_ISSUE_NUMBER")
    run_dir = RUN_ROOT / f"issue_{number}"
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if run_dir.is_symlink():
        raise ValueError("UNSAFE_RUN_DIR")
    try:
        (run_dir / ".scripted_fixture_v1_claimed").mkdir(mode=0o700)
    except FileExistsError:
        return False
    return True


def run_scripted_fixture(job) -> dict:
    """Use trusted internal HTML only; never issue a paid AI/model call."""
    from cloud_api import DEMO_HTML
    runner = MiniFishRunner(
        ScriptedPlanner(job.actions), max_steps=4,
        max_duration_seconds=40, headless=True,
        profile_path=None, session_vault=None,
        capture_dir=None, log_path=None,
    )
    state = runner.run(
        goal=job.goal, start_url="about:blank", start_html=DEMO_HTML,
    )
    return verify_scripted_fixture_state(state, job)


def run_job(issue: dict, *, private_mailbox=None, validated_scripted_job=None) -> dict:
    payload = json.loads(issue.get("body") or "{}")
    mode = payload.get("mode", "demo")
    goal = str(payload.get("goal") or "").strip()
    url = str(payload.get("url") or "").strip()

    if not goal:
        raise ValueError("goal is required")

    issue_no = int(issue["number"])
    run_dir = RUN_ROOT / f"issue_{issue_no}"

    if mode == SCRIPTED_MODE:
        if not _scripted_enabled():
            raise ValueError("SCRIPTED_FIXTURE_DISABLED")
        job = validated_scripted_job
        if job is None:
            job = parse_scripted_fixture_issue(issue, owner=OWNER)
        return run_scripted_fixture(job)

    if mode == "owner_status":
        # Owner-authorized internal-only status. No website visit, cookie,
        # screenshot, API key, request header or raw log leaves Codespaces.
        from minifish.owner_runtime import diagnose
        report = diagnose()
        return {
            "mode": "owner_status",
            "run_id": f"issue_{issue_no}",
            "status": report["status"],
            "can_start": bool(report["can_start"]),
            "external_web_calls": 0,
            "website_writes": 0,
            "credential_values_included": False,
            "owner_login_verified": False,
        }

    if mode == "owner_private_delivery_mock":
        # STRICTLY SYNTHETIC, test-only. The active Codespace's worker cannot
        # receive this command and has no real private-result endpoint.
        if (os.getenv("CODESPACE_NAME")
                or os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") != "1"
                or "PYTEST_CURRENT_TEST" not in os.environ):
            raise ValueError("PRIVATE_DELIVERY_MOCK_DISABLED")
        if set(payload) != {"mode", "goal"} or goal != "READ_SYNTHETIC_JOB_TITLES":
            raise ValueError("PRIVATE_DELIVERY_CONTRACT_BLOCKED")
        from minifish.private_result_mailbox import PrivateResultMailbox
        from minifish.owner_read_mock import run_mock_read
        if not isinstance(private_mailbox, PrivateResultMailbox):
            raise ValueError("PRIVATE_DELIVERY_CHANNEL_REQUIRED")
        proof = run_mock_read()
        if proof.status != "PASS":
            raise ValueError("SYNTHETIC_SOURCE_NOT_CONFIRMED")
        private_mailbox.publish(job_id=f"issue_{issue_no}", titles=proof.titles)
        # GitHub-visible return: no title text, count, capability or link.
        return private_mailbox.public_receipt(f"issue_{issue_no}")

    if mode == "owner_read_mock":
        # TEST-ONLY: never dispatch this branch from a running Codespace
        # or a real GitHub Issue. There is NO production owner-read command.
        if (os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") != "1"
                or "PYTEST_CURRENT_TEST" not in os.environ):
            raise ValueError("SYNTHETIC_OWNER_READ_DISABLED")
        if set(payload) != {"mode", "goal"} or goal != "READ_SYNTHETIC_JOB_TITLES":
            raise ValueError("SYNTHETIC_OWNER_READ_CONTRACT_BLOCKED")
        from minifish.owner_read_mock import run_mock_read
        # Return safe receipt only. No fake title, fake cookie or page body.
        return {"run_id": f"issue_{issue_no}", **run_mock_read().public_receipt()}

    if mode == "read_only":
        # One-shot GitHub Actions route. No OpenAIPlanner, login, cookies or clicks.
        from minifish.readonly_probe import run_public_readonly
        return run_public_readonly(
            job_id=f"issue_{issue_no}", goal=goal, url=url,
            run_dir=run_dir,
        )

    if mode == "demo":
        planner = ScriptedPlanner([
            Action(type="click", role="button", name="プロフィール"),
            Action(type="fill", role="textbox", name="表示名", value="ヒデロック"),
            Action(type="click", role="button", name="保存"),
            Action(type="done", result="プロフィールを保存完了"),
        ])
        from cloud_api import DEMO_HTML
        start_url = "about:blank"
        start_html = DEMO_HTML
    elif mode == "agent":
        if os.getenv("MINIFISH_ALLOW_PAID_BRIDGE_AGENT") != "1":
            raise ValueError("PAID_AGENT_DISABLED_BY_DEFAULT")
        if not url.startswith(("http://", "https://")):
            raise ValueError("agent mode requires an http(s) url")
        planner = OpenAIPlanner()
        start_url = url
        start_html = None
    else:
        raise ValueError("mode must be demo or agent")

    runner = MiniFishRunner(
        planner,
        max_steps=25,
        max_duration_seconds=180,
        headless=True,
        profile_path=None,  # Never persist live login cookies in legacy plaintext JSON
        capture_dir=str(run_dir / "captures"),
        log_path=str(run_dir / "run.json"),
    )
    state = runner.run(goal=goal, start_url=start_url, start_html=start_html)
    last = state.events[-1] if state.events else None
    return {
        "run_id": state.run_id,
        "status": state.status,
        "step_count": state.step_count,
        "current_url": last.after_url if last else start_url,
        "result": state.final_result,
        "error": state.error,
    }


def main() -> None:
    print("MiniFish bridge status: " + issue_transport.transport_ready(), flush=True)
    seen: set[int] = set()

    while True:
        try:
            for issue in list_jobs():
                number = int(issue["number"])
                if number in seen:
                    continue
                seen.add(number)
                try:
                    validated = preflight_issue(issue)
                except (InputContractError, ValueError) as exc:
                    # Preflight failures are NOT accepted. Only fixed codes
                    # ever reach public Issue comments.
                    code = str(exc)
                    allowed_codes = {
                        "INVALID_ISSUE_BODY", "INVALID_ISSUE_JSON",
                        "INVALID_ISSUE_PAYLOAD", "GOAL_REQUIRED",
                        "SCRIPTED_FIXTURE_DISABLED", "PAID_AGENT_DISABLED_BY_DEFAULT",
                        "INVALID_AGENT_START_URL", "UNRECOGNIZED_MODE",
                    }
                    if isinstance(exc, InputContractError):
                        code = "SCRIPTED_INPUT_BLOCKED"
                    elif code not in allowed_codes:
                        code = "INVALID_JOB_INPUT"
                    comment(number, "🐟 MiniFish Bridge BLOCKED: " + code)
                    close(number)
                    continue
                if validated is not None and not claim_scripted_issue(number):
                    # A previously claimed issue might still be RUNNING.
                    # Never close it or post a misleading terminal result.
                    continue
                try:
                    comment(number, "🐟 MiniFish Bridge accepted this job.")
                    result = run_job(issue, validated_scripted_job=validated)
                    comment(number, "MiniFish result:\n" + json.dumps(result, ensure_ascii=False, indent=2))
                    close(number)
                except Exception as exc:
                    comment(
                        number,
                        "🐟 MiniFish Bridge failed.\n\n"
                        + "ERROR_TYPE=" + type(exc).__name__,
                    )
                    close(number)
        except issue_transport.BridgeTransportError as exc:
            # Fixed machine-readable error only, never secrets or raw body.
            print("bridge transport: " + str(exc), flush=True)
            if issue_transport.transport_ready() == "BLOCKED_NO_GITHUB_AUTH":
                time.sleep(max(POLL_SECONDS, 60))
                continue
        except Exception as exc:
            print("bridge loop error: " + type(exc).__name__, flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
