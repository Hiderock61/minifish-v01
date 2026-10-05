from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
from typing import Any

from .models import Action, Observation


class Planner(ABC):
    @abstractmethod
    def next_action(self, goal: str, observation: Observation, history: list[dict[str, Any]]) -> Action:
        raise NotImplementedError


class ScriptedPlanner(Planner):
    """Deterministic planner for proving the browser loop without any paid AI call."""

    def __init__(self, actions: list[Action]):
        self.actions = list(actions)
        self.i = 0

    def next_action(self, goal: str, observation: Observation, history: list[dict[str, Any]]) -> Action:
        if self.i >= len(self.actions):
            return Action(type="done", result="Script completed", reason="No scripted actions left")
        a = self.actions[self.i]
        self.i += 1
        return a


class OpenAIPlanner(Planner):
    """
    Optional AI seed. Requires OPENAI_API_KEY and OPENAI_MODEL.
    Uses the current Responses API through the installed OpenAI Python client.
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("OPENAI_MODEL")
        if not self.model:
            raise RuntimeError("Set OPENAI_MODEL to an API model available to your account")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")

        from openai import OpenAI
        self.client = OpenAI()

    def next_action(self, goal: str, observation: Observation, history: list[dict[str, Any]]) -> Action:
        action_contract = {
            "goto": {"type": "goto", "url": "https://...", "reason": "..."},
            "click": {"type": "click", "role": "button|link|textbox|...", "name": "visible accessible name", "reason": "..."},
            "fill": {"type": "fill", "role": "textbox", "name": "accessible name", "value": "text", "reason": "..."},
            "press": {"type": "press", "key": "Enter", "reason": "..."},
            "back": {"type": "back", "reason": "..."},
            "wait": {"type": "wait", "seconds": 1, "reason": "..."},
            "done": {"type": "done", "result": "goal result", "reason": "..."},
            "fail": {"type": "fail", "error": "why goal cannot continue", "reason": "..."},
        }
        prompt = f"""You are the planning brain for a browser agent.
Choose EXACTLY ONE next action toward the GOAL.
Use the accessibility snapshot first. Do not invent controls not present in the observation.
Return one JSON object only, no markdown.

GOAL:
{goal}

CURRENT OBSERVATION:
{observation.compact()}

RECENT HISTORY:
{json.dumps(history[-6:], ensure_ascii=False)[:8000]}

ALLOWED ACTION SHAPES:
{json.dumps(action_contract, ensure_ascii=False)}
"""
        response = self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": prompt}],
        )
        raw = response.output_text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        data = json.loads(raw)
        return Action.from_dict(data)
