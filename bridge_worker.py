from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from minifish import Action, MiniFishRunner, OpenAIPlanner, ScriptedPlanner
from minifish import github_issue_transport as issue_transport

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


def run_job(issue: dict) -> dict:
    payload = json.loads(issue.get("body") or "{}")
    mode = payload.get("mode", "demo")
    goal = str(payload.get("goal") or "").strip()
    url = str(payload.get("url") or "").strip()

    if not goal:
        raise ValueError("goal is required")

    issue_no = int(issue["number"])
    run_dir = RUN_ROOT / f"issue_{issue_no}"

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
                    comment(number, "🐟 MiniFish Bridge accepted this job.")
                    result = run_job(issue)
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
