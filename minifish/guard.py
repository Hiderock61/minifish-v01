from __future__ import annotations

from collections import Counter
from typing import Any

from .models import Action, Observation


class SupervisorGate:
    """Deterministic pre-action supervisor.

    The gate sits between PLAN and ACTION. It blocks obvious loops,
    asks for replanning on URL ping-pong, and stops before high-impact
    actions that require a human.
    """

    HUMAN_TERMS = (
        "送信", "購入", "注文", "契約", "削除", "退会", "解約",
        "応募", "申込", "申し込", "支払", "決済", "公開", "投稿",
        "予約", "確定",
        "submit", "purchase", "buy", "order", "contract", "delete",
        "close account", "apply", "pay", "payment", "publish", "post",
        "book", "confirm",
    )

    def __init__(self, repeat_limit: int = 3):
        self.repeat_limit = repeat_limit

    def check(
        self,
        action: Action,
        observation: Observation,
        history: list[dict[str, Any]],
    ) -> tuple[str, str]:
        # Terminal actions are always allowed.
        if action.type in ("done", "fail"):
            return "PASS", "terminal action"

        # Same current URL + same proposed action repeated too many times.
        signature = self._signature(action, observation.url)
        signatures = [h.get("signature") for h in history]
        if Counter(signatures)[signature] >= self.repeat_limit - 1:
            return "STOP", f"repeated action at same URL reached limit {self.repeat_limit}"

        # Obvious 404 page repeated twice.
        lower = (observation.title + "\n" + observation.text_excerpt).lower()
        if "404" in lower:
            recent_404 = sum(1 for h in history[-2:] if h.get("page_404"))
            if recent_404 >= 1:
                return "STOP", "404 observed twice"

        # A -> B -> A -> B route pattern. Do not execute another action yet.
        route = [h.get("url") for h in history[-3:]] + [observation.url]
        if (
            len(route) == 4
            and all(route)
            and route[0] == route[2]
            and route[1] == route[3]
            and route[0] != route[1]
        ):
            return "REPLAN", f"URL ping-pong detected: {route[0]} <-> {route[1]}"

        # High-impact clicks stop before execution and wait for a human.
        human_reason = self._human_gate_reason(action)
        if human_reason:
            return "HUMAN", human_reason

        return "PASS", "no supervisor-rule violation"

    @classmethod
    def _human_gate_reason(cls, action: Action) -> str | None:
        if action.type != "click":
            return None
        haystack = " ".join(
            str(x or "")
            for x in [action.name, action.selector, action.reason]
        ).lower()
        for term in cls.HUMAN_TERMS:
            if term.lower() in haystack:
                return f"human approval required before high-impact action: {term}"
        return None

    @staticmethod
    def _signature(action: Action, url: str) -> str:
        return "|".join(
            str(x or "")
            for x in [
                url,
                action.type,
                action.url,
                action.role,
                action.name,
                action.selector,
                action.value,
                action.key,
            ]
        )


# Backward-compatible name used by older MiniFish code/tests.
RunGuard = SupervisorGate
