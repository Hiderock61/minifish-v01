from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import json
import time

from .models import Action, Event, RunState, now_iso
from .browser import PlaywrightBrowser
from .planner import Planner
from .guard import RunGuard


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
        self.capture_dir = capture_dir
        self.log_path = Path(log_path) if log_path else None
        self.on_event = on_event
        self.should_stop = should_stop
        self.guard = RunGuard()

    def run(
        self,
        goal: str,
        start_url: str = "about:blank",
        start_html: str | None = None,
        run_id: str | None = None,
    ) -> RunState:
        state = RunState(goal=goal, start_url=start_url, **({"run_id": run_id} if run_id else {}))
        state.status = "RUNNING"
        started = time.monotonic()
        history: list[dict[str, Any]] = []

        try:
            with PlaywrightBrowser(
                headless=self.headless,
                executable_path=self.executable_path,
                profile_path=self.profile_path,
                capture_dir=self.capture_dir,
            ) as browser:
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
                    screenshot = browser.screenshot(step)
                    html_capture = browser.html_capture(step)

                    action = self.planner.next_action(state.goal, observation, history)
                    decision, reason = self.guard.check(action, observation, history)

                    signature = self.guard._signature(action, observation.url)
                    page_404 = "404" in (observation.title + "\n" + observation.text_excerpt).lower()

                    if decision == "STOP":
                        execution = {"ok": False, "stopped": True, "reason": reason}
                        event = Event(
                            step=step,
                            at=now_iso(),
                            before_url=before_url,
                            observation={
                                "url": observation.url,
                                "title": observation.title,
                                "aria_snapshot": observation.aria_snapshot,
                                "text_excerpt": observation.text_excerpt,
                                "screenshot": screenshot,
                                "html_capture": html_capture,
                            },
                            proposed_action=action.__dict__,
                            decision=f"STOP: {reason}",
                            execution_result=execution,
                            after_url=browser.current_url,
                        )
                        state.events.append(event)
                        state.status = "FAILED"
                        state.error = reason
                        self._notify(state, event)
                        break

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
                        before_url=before_url,
                        observation={
                            "url": observation.url,
                            "title": observation.title,
                            "aria_snapshot": observation.aria_snapshot,
                            "text_excerpt": observation.text_excerpt,
                            "screenshot": screenshot,
                            "html_capture": html_capture,
                        },
                        proposed_action=action.__dict__,
                        decision="PASS",
                        execution_result=execution,
                        after_url=browser.current_url,
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

                    if state.status in ("COMPLETED", "FAILED", "CANCELLED"):
                        break
                else:
                    state.status = "FAILED"
                    state.error = f"max_steps exceeded ({self.max_steps})"

        except Exception as e:
            state.status = "FAILED"
            state.error = f"{type(e).__name__}: {e}"

        state.ended_at = now_iso()
        self._save(state)
        return state

    def _notify(self, state: RunState, event: Event) -> None:
        if self.on_event:
            self.on_event(state, event)

    def _save(self, state: RunState) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
