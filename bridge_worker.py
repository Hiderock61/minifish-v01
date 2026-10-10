from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import traceback

from minifish import Action, MiniFishRunner, OpenAIPlanner, ScriptedPlanner

REPO = os.getenv("MINIFISH_BRIDGE_REPO", "Hiderock61/minifish-v01")
OWNER = os.getenv("MINIFISH_BRIDGE_OWNER", "Hiderock61")
POLL_SECONDS = float(os.getenv("MINIFISH_BRIDGE_POLL_SECONDS", "5"))
RUN_ROOT = Path(os.getenv("MINIFISH_RUN_ROOT", ".minifish/runs"))
PROFILE_PATH = os.getenv("MINIFISH_PROFILE_PATH", ".minifish/profile.json")


def gh(*args: str) -> str:
    p = subprocess.run(["gh", *args], check=True, text=True, capture_output=True)
    return p.stdout


def list_jobs() -> list[dict]:
    raw = gh(
        "issue", "list",
        "--repo", REPO,
        "--state", "open",
        "--search", "[MINIFISH JOB] in:title",
        "--limit", "20",
        "--json", "number,title,body,author",
    )
    jobs = json.loads(raw)
    return [
        j for j in jobs
        if j.get("title", "").startswith("[MINIFISH JOB]")
        and (j.get("author") or {}).get("login") == OWNER
    ]


def comment(number: int, text: str) -> None:
    gh("issue", "comment", str(number), "--repo", REPO, "--body", text)


def close(number: int) -> None:
    gh("issue", "close", str(number), "--repo", REPO)


def run_job(issue: dict) -> dict:
    payload = json.loads(issue.get("body") or "{}")
    mode = payload.get("mode", "demo")
    goal = str(payload.get("goal") or "").strip()
    url = str(payload.get("url") or "").strip()

    if not goal:
        raise ValueError("goal is required")

    issue_no = int(issue["number"])
    run_dir = RUN_ROOT / f"issue_{issue_no}"

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
        profile_path=PROFILE_PATH,
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
    print(f"MiniFish GitHub Bridge watching {REPO} for jobs from {OWNER}", flush=True)
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
                        + f"{type(exc).__name__}: {exc}\n"
                        + traceback.format_exc(limit=3),
                    )
                    close(number)
        except Exception as exc:
            print(f"bridge loop error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
