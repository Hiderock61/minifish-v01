from minifish.models import Action, Observation, RunState
from minifish.planner import ScriptedPlanner


def test_run_state_serializes_human_facts():
    state = RunState(
        goal="open profile",
        start_url="https://example.com",
        human_facts=["login is already confirmed", "do not revisit /old-profile"],
    )
    payload = state.to_dict()
    assert payload["human_facts"] == [
        "login is already confirmed",
        "do not revisit /old-profile",
    ]


def test_scripted_planner_accepts_human_facts_without_reinterpreting_them():
    planner = ScriptedPlanner([Action(type="done", result="ok")])
    obs = Observation(
        url="https://example.com",
        title="Example",
        aria_snapshot="",
        text_excerpt="",
    )
    action = planner.next_action(
        "finish",
        obs,
        [],
        ["human already confirmed authentication"],
    )
    assert action.type == "done"
    assert action.result == "ok"
