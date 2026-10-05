from __future__ import annotations

from collections import Counter
from typing import Any

from .models import Action, Observation


class RunGuard:
    """Hard, deterministic safety rails. No AI needed."""

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

        # Same current URL + same proposed action repeated too many times = likely loop.
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

        return "PASS", "no hard-rule violation"

    @staticmethod
    def _signature(action: Action, url: str) -> str:
        return "|".join(
            str(x or "")
            for x in [url, action.type, action.url, action.role, action.name, action.selector, action.value, action.key]
        )
