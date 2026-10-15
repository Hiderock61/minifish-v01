"""MiniFish mission commander v0.1.

Receives a job, checks its authority and budget, selects an existing
runner, supervises actions through MiniFishRunner's SupervisorGate,
verifies the result and returns a safe public status.

Only the internal DEMO route is executable in v0.1. The installed
OpenAIPlanner is NOT automatically enabled by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re

from .models import Action
from .planner import ScriptedPlanner
from .runner import MiniFishRunner


@dataclass(frozen=True)
class Mission:
    job_id: str
    goal: str
    route: str = "internal_demo"
    action_class: str = "local_demo"
    max_paid_calls: int = 0
    output_root: str = "command_tower_runs"


@dataclass(frozen=True)
class TowerDecision:
    state: str
    reason: str


class MiniFishCommandTower:
    """Safe mission layer ABOVE the already existing planner/guard/runner."""

    def __init__(self) -> None:
        self.seen_job_ids: set[str] = set()

    @staticmethod
    def preflight(mission: Mission) -> TowerDecision:
        if not mission.job_id.strip() or not mission.goal.strip():
            return TowerDecision("STOP", "MISSING_JOB_ID_OR_GOAL")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", mission.job_id):
            return TowerDecision("STOP", "INVALID_JOB_ID")
        if mission.max_paid_calls != 0:
            return TowerDecision("HUMAN", "API_BUDGET_NOT_AUTHORIZED")
        if mission.action_class != "local_demo":
            return TowerDecision("HUMAN", "HIGH_IMPACT_OR_EXTERNAL_ACTION")
        if mission.route != "internal_demo":
            return TowerDecision("HUMAN", "EXTERNAL_ROUTE_NOT_AUTHORIZED")
        return TowerDecision("PASS", "SAFE_LOCAL_MOCK")

    @staticmethod
    def preflight_public_readonly(job_id: str, goal: str, url: str) -> TowerDecision:
        """A deliberately narrow, credential-free real-web gate for issue commands.

        No user-provided URL is permitted beyond the one static public fixture.
        The goal is recorded as data; it never becomes an AI instruction.
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", job_id):
            return TowerDecision("STOP", "INVALID_JOB_ID")
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 200:
            return TowerDecision("STOP", "INVALID_READ_ONLY_GOAL")
        if url not in ("https://example.com", "https://example.com/"):
            return TowerDecision("STOP", "URL_NOT_ALLOWLISTED")
        return TowerDecision("PASS", "PUBLIC_READ_ONLY_FIXED_URL")

    def execute(self, mission: Mission) -> dict[str, Any]:
        # Check duplicate BEFORE side effects. A future remote worker needs
        # a persistent cross-process/idempotency lock; this is local only.
        if mission.job_id in self.seen_job_ids:
            return self._hold(mission.job_id, "STOP", "DUPLICATE_JOB_LOCAL")
        decision = self.preflight(mission)
        if decision.state != "PASS":
            return self._hold(mission.job_id, decision.state, decision.reason)
        self.seen_job_ids.add(mission.job_id)

        # The goal is data, not instructions for an external browser.
        # All actions and HTML are fixed inside a local synthetic fixture.
        from demo_run import DEMO_HTML
        actions = [
            Action(type="click", role="button", name="プロフィール"),
            Action(type="fill", role="textbox", name="表示名", value="BONSAI_TEST"),
            Action(type="click", role="button", name="保存"),
            Action(type="done", result="local demo finished"),
        ]
        output = Path(mission.output_root) / mission.job_id
        output.mkdir(parents=True, exist_ok=True)
        runner = MiniFishRunner(
            ScriptedPlanner(actions), max_steps=8, max_duration_seconds=45,
            headless=True, profile_path=None,
            capture_dir=str(output / "captures"),
            log_path=str(output / "private_run.json"),
        )
        state = runner.run(
            goal=mission.goal, start_url="about:blank", start_html=DEMO_HTML,
        )
        # 'done' alone does not establish that the page reached the goal.
        actually_saved = any(
            "保存完了" in str(event.observation.get("text_excerpt", ""))
            for event in state.events
        )
        expected_actions = ["click", "fill", "click", "done"]
        actual_actions = [row.action_type for row in state.ledger]
        guarded = all(row.decision == "PASS" for row in state.ledger)
        verified = (state.status == "COMPLETED" and actually_saved
                    and actual_actions == expected_actions and guarded)
        report = {
            "job_id": mission.job_id,
            "state": "COMPLETE" if verified else "STOP",
            "result": "PASS" if verified else "FAIL",
            "run_id": state.run_id,
            "steps": state.step_count,
            "route": "internal_demo",
            "plan_source": "ScriptedPlanner (no API call)",
            "ai_planner": "INSTALLED_BUT_NOT_ACTIVATED",
            "checks": {
                "saved_visible": actually_saved,
                "action_sequence": actual_actions == expected_actions,
                "supervisor_decisions_all_pass": guarded,
            },
            "api_calls": 0,
            "external_writes": 0,
            "paid_calls": 0,
            "error_layer": None if verified else "EXECUTION_OR_VERIFICATION",
        }
        (output / "public_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report

    @staticmethod
    def _hold(job_id: str, state: str, reason: str) -> dict[str, Any]:
        return {
            "job_id": job_id, "state": state, "result": "NOT_EXECUTED",
            "reason": reason, "api_calls": 0, "external_writes": 0,
            "paid_calls": 0,
        }
