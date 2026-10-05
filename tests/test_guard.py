from minifish.guard import RunGuard
from minifish.models import Action, Observation


def test_repeat_guard_stops_third_same_action():
    g = RunGuard(repeat_limit=3)
    obs = Observation(url="https://example.com/a", title="A", aria_snapshot="", text_excerpt="")
    act = Action(type="click", role="button", name="Next")
    sig = g._signature(act, obs.url)
    history = [
        {"signature": sig, "page_404": False},
        {"signature": sig, "page_404": False},
    ]
    decision, _ = g.check(act, obs, history)
    assert decision == "STOP"


def test_404_twice_stops():
    g = RunGuard()
    obs = Observation(url="https://example.com/x", title="404 Not Found", aria_snapshot="", text_excerpt="")
    decision, _ = g.check(Action(type="back"), obs, [{"signature": "x", "page_404": True}])
    assert decision == "STOP"
