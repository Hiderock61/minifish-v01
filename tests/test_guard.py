from minifish.guard import SupervisorGate
from minifish.models import Action, Observation


def test_repeat_guard_stops_third_same_action():
    g = SupervisorGate(repeat_limit=3)
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
    g = SupervisorGate()
    obs = Observation(url="https://example.com/x", title="404 Not Found", aria_snapshot="", text_excerpt="")
    decision, _ = g.check(Action(type="back"), obs, [{"signature": "x", "page_404": True}])
    assert decision == "STOP"


def test_url_ping_pong_requests_replan():
    g = SupervisorGate()
    history = [
        {"url": "https://example.com/a", "signature": "a", "page_404": False},
        {"url": "https://example.com/b", "signature": "b", "page_404": False},
        {"url": "https://example.com/a", "signature": "c", "page_404": False},
    ]
    obs = Observation(url="https://example.com/b", title="B", aria_snapshot="", text_excerpt="")
    decision, reason = g.check(Action(type="click", role="link", name="Continue"), obs, history)
    assert decision == "REPLAN"
    assert "ping-pong" in reason


def test_high_impact_click_requires_human():
    g = SupervisorGate()
    obs = Observation(url="https://example.com/checkout", title="Checkout", aria_snapshot="", text_excerpt="")
    decision, _ = g.check(Action(type="click", role="button", name="購入を確定"), obs, [])
    assert decision == "HUMAN"


def test_safe_save_click_passes():
    g = SupervisorGate()
    obs = Observation(url="https://example.com/profile", title="Profile", aria_snapshot="", text_excerpt="")
    decision, _ = g.check(Action(type="click", role="button", name="保存", reason="submit form"), obs, [])
    assert decision == "PASS"
