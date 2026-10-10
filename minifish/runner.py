from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import json
import time

from .models import Action, Event, LedgerEntry, RunState, now_iso
from .browser import PlaywrightBrowser
from .planner import Planner
from .guard import SupervisorGate
from .auth import SiteAuth, check_login, origin, public_url, preflight_action


class AuthRequired(Exception):
    pass



class MiniFishRunner:
    """Goal -> observe -> plan -> guard -> act -> observe loop."""

    def __init__(
        self,
        planner: Planner,
        *,
        max_steps: int = 25,
        max_duration_seconds: int = 180,
        headless: bool = True,
        executable_path: str | None = None,
        profile_path: str | None = None,
        auth_site: SiteAuth | None = None,
        capture_dir: str | None = None,
        log_path: str | None = None,
        on_event: Callable[[RunState, Event], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.planner = planner
        self.max_steps = max_steps
        self.max_duration_seconds = max_duration_seconds
        self.headless = headless
        self.executable_path = executable_path
        self.profile_path = profile_path
        self.auth_site = auth_site
        self.private_mode = auth_site is not None
        self.capture_dir = capture_dir
        self.log_path = Path(log_path) if log_path else None
        self.on_event = on_event
        self.should_stop = should_stop
        self.guard = SupervisorGate()

    def run(
        self,
        goal: str,
        start_url: str = "about:blank",
        start_html: str | None = None,
        run_id: str | None = None,
        human_facts: list[str] | None = None,
    ) -> RunState:
        state = RunState(
            goal=goal,
            start_url=start_url,
            human_facts=list(human_facts or []),
            **({"run_id": run_id} if run_id else {}),
        )
        state.status = "RUNNING"
        started = time.monotonic()
        history: list[dict[str, Any]] = []

        if self.auth_site and (not self.profile_path or not Path(self.profile_path).is_file()):
            state.status = "WAITING"
            state.final_result = "AUTH_REQUIRED: session file missing. Human login needed."
            state.ended_at = now_iso()
            self._save(state)
            return state

        try:
            with PlaywrightBrowser(
                headless=self.headless,
                executable_path=self.executable_path,
                profile_path=self.profile_path,
                capture_dir=None if self.private_mode else self.capture_dir,
                save_profile_on_close=not self.private_mode,
            ) as browser:
                if self.auth_site:
                    if not check_login(browser, self.auth_site):
                        raise AuthRequired("AUTH_REQUIRED: session expired or login not confirmed.")
                    # Only the dedicated, human-verified sign-in program writes credentials.
                    # Routine Agent runs read the session and never overwrite it.
                    browser.save_profile_on_close = False
                if start_html is not None:
                    assert browser.page is not None
                    browser.page.set_content(start_html, wait_until="domcontentloaded")
                else:
                    browser.goto(start_url)

                for step in range(1, self.max_steps + 1):
                    if self.should_stop and self.should_stop():
                        state.status = "CANCELLED"
                        state.final_result = "cancelled by user"
                        break
                    if time.monotonic() - started > self.max_duration_seconds:
                        raise TimeoutError("max_duration_seconds exceeded")

                    state.step_count = step
                    before_url = browser.current_url
                    observation = browser.observe()
                    if self.auth_site and (
                        origin(observation.url) != origin(self.auth_site.base_url)
                        or self.auth_site.login_detected(observation.url)
                    ):
                        browser.save_profile_on_close = False
                        raise AuthRequired("AUTH_REQUIRED: login/redirect detected during run.")
                    screenshot = None if self.private_mode else browser.screenshot(step)
                    html_capture = None if self.private_mode else browser.html_capture(step)
                    recorded_observation = {
                        "url": public_url(observation.url) if self.private_mode else observation.url,
                        "title": "[private]" if self.private_mode else observation.title,
                        "aria_snapshot": "[redacted]" if self.private_mode else observation.aria_snapshot,
                        "text_excerpt": "[redacted]" if self.private_mode else observation.text_excerpt,
                        "screenshot": screenshot,
                        "html_capture": html_capture,
                    }

                    action = self.planner.next_action(state.goal, observation, history, state.human_facts)
                    decision, reason = self.guard.check(action, observation, history)
                    if self.auth_site and decision == "PASS":
                        policy = preflight_action(self.auth_site, action)
                        if policy:
                            decision, reason = "HUMAN", policy

                    recorded_action = {
                        **action.__dict__,
                        "value": "[redacted]" if self.private_mode and action.value is not None else action.value,
                        "result": "[redacted]" if self.private_mode and action.result is not None else action.result,
                    }
                    signature = self.guard._signature(action, observation.url)
                    page_404 = "404" in (observation.title + "\n" + observation.text_excerpt).lower()

                    if decision == "STOP":
                        execution = {"ok": False, "stopped": True, "reason": reason}
                        event = Event(
                            step=step,
                            at=now_iso(),
                            before_url=public_url(before_url) if self.private_mode else before_url,
                            observation=recorded_observation,
                            proposed_action=recorded_action,
                            decision=f"STOP: {reason}",
                            execution_result=execution,
                            after_url=public_url(browser.current_url) if self.private_mode else browser.current_url,
                        )
                        state.events.append(event)
                        state.status = "FAILED"
                        state.error = reason
                        self._notify(state, event)
                        break

                    if decision == "HUMAN":
                        execution = {"ok": False, "human_required": True, "reason": reason}
                        event = Event(
                            step=step,
                            at=now_iso(),
                            before_url=public_url(before_url) if self.private_mode else before_url,
                            observation=recorded_observation,
                            proposed_action=recorded_action,
                            decision=f"HUMAN: {reason}",
                            execution_result=execution,
                            after_url=public_url(browser.current_url) if self.private_mode else browser.current_url,
                        )
                        state.events.append(event)
                        state.status = "WAITING"
                        state.final_result = "human approval required"
                        self._notify(state, event)
                        break

                    if decision == "REPLAN":
                        execution = {"ok": False, "replan": True, "reason": reason}
                        event = Event(
                            step=step,
                            at=now_iso(),
                            before_url=public_url(before_url) if self.private_mode else before_url,
                            observation=recorded_observation,
                            proposed_action=recorded_action,
                            decision=f"REPLAN: {reason}",
                            execution_result=execution,
                            after_url=public_url(browser.current_url) if self.private_mode else browser.current_url,
                        )
                        state.events.append(event)
                        history.append(
                            {
                                "step": step,
                                "url": observation.url,
                                "action": action.__dict__,
                                "after_url": browser.current_url,
                                "signature": signature,
                                "page_404": page_404,
                                "decision": "REPLAN",
                                "result": execution,
                            }
                        )
                        self._notify(state, event)
                        continue

                    if action.type == "done":
                        execution = {"ok": True, "terminal": True}
                        state.status = "COMPLETED"
                        state.final_result = action.result or action.reason or "completed"
                    elif action.type == "fail":
                        execution = {"ok": False, "terminal": True}
                        state.status = "FAILED"
                        state.error = action.error or action.reason or "planner failed"
                    else:
                        execution = browser.execute(action)

                    event = Event(
                        step=step,
                        at=now_iso(),
                        before_url=public_url(before_url) if self.private_mode else before_url,
                        observation=recorded_observation,
                        proposed_action=recorded_action,
                        decision="PASS",
                        execution_result=execution,
                        after_url=public_url(browser.current_url) if self.private_mode else browser.current_url,
                    )
                    state.events.append(event)
                    self._notify(state, event)
                    history.append(
                        {
                            "step": step,
                            "url": observation.url,
                            "action": action.__dict__,
                            "after_url": browser.current_url,
                            "signature": signature,
                            "page_404": page_404,
                            "result": execution,
                        }
                    )

                    if state.status in ("WAITING", "COMPLETED", "FAILED", "CANCELLED"):
                        break
                else:
                    state.status = "FAILED"
                    state.error = f"max_steps exceeded ({self.max_steps})"

        except AuthRequired as e:
            state.status = "WAITING"
            state.final_result = str(e)
        except Exception as e:
            state.status = "FAILED"
            state.error = f"{type(e).__name__}: {e}"

        state.ended_at = now_iso()
        self._save(state)
        return state

    def _notify(self, state: RunState, event: Event) -> None:
        action = event.proposed_action or {}
        target = (
            action.get("name")
            or action.get("url")
            or action.get("selector")
            or action.get("key")
            or action.get("value")
            or ""
        )
        execution = event.execution_result or {}
        summary = (
            execution.get("reason")
            or execution.get("error")
            or execution.get("result")
            or ("ok" if execution.get("ok") else "no-op")
        )
        state.ledger.append(
            LedgerEntry(
                step=event.step,
                at=event.at,
                current_url=event.after_url or event.before_url,
                action_type=str(action.get("type") or ""),
                action_target=str(target),
                decision=event.decision,
                result_summary=str(summary),
            )
        )
        if self.on_event:
            self.on_event(state, event)

    def _save(self, state: RunState) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
