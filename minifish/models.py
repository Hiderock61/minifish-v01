from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Literal
import uuid

RunStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
ActionType = Literal["goto", "click", "fill", "press", "back", "wait", "done", "fail"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Observation:
    url: str
    title: str
    aria_snapshot: str
    text_excerpt: str

    def compact(self, max_chars: int = 6000) -> str:
        s = (
            f"URL: {self.url}\n"
            f"TITLE: {self.title}\n"
            f"ACCESSIBILITY:\n{self.aria_snapshot}\n"
            f"TEXT:\n{self.text_excerpt}"
        )
        return s[:max_chars]


@dataclass
class Action:
    type: ActionType
    reason: str = ""
    url: str | None = None
    role: str | None = None
    name: str | None = None
    value: str | None = None
    selector: str | None = None
    key: str | None = None
    seconds: float | None = None
    result: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Action":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in d.items() if k in allowed}
        if "type" not in clean:
            raise ValueError("Action requires type")
        return cls(**clean)


@dataclass
class Event:
    step: int
    at: str
    before_url: str
    observation: dict[str, Any]
    proposed_action: dict[str, Any]
    decision: str
    execution_result: dict[str, Any]
    after_url: str


@dataclass
class RunState:
    goal: str
    start_url: str
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:16]}")
    status: RunStatus = "PENDING"
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    step_count: int = 0
    final_result: str | None = None
    error: str | None = None
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
