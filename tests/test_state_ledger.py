from minifish.models import Action, Event, RunState
from minifish.planner import ScriptedPlanner
from minifish.runner import MiniFishRunner


def test_notify_records_compact_ledger_entry():
    runner = MiniFishRunner(ScriptedPlanner([]))
    state = RunState(goal="g", start_url="about:blank")
    event = Event(
        step=1,
        at="2026-10-10T00:00:00+00:00",
        before_url="https://example.com/a",
        observation={},
        proposed_action=Action(type="click", role="button", name="Next").__dict__,
        decision="PASS",
        execution_result={"ok": True},
        after_url="https://example.com/b",
    )

    runner._notify(state, event)

    assert len(state.ledger) == 1
    item = state.ledger[0]
    assert item.step == 1
    assert item.current_url == "https://example.com/b"
    assert item.action_type == "click"
    assert item.action_target == "Next"
    assert item.decision == "PASS"
    assert item.result_summary == "ok"
