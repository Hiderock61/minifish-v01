import json
from threading import Event
from types import SimpleNamespace
import pytest
from minifish import crowdworks_handoff as cw

class Page:
    url = cw.LOGIN_URL
    closed = False
    def is_closed(self): return self.closed
    def wait_for_timeout(self, ms):
        self.pumps += 1
        self.finish.set()
    def __init__(self, finish):
        self.finish=finish
        self.pumps=0

def manager():
    m=cw.OwnerLoginHandoff()
    m._record_navigation(200,cw.LOGIN_URL)
    return m

def test_manual_wait_pumps_browser_callbacks():
    finish=Event()
    page=Page(finish)
    manager()._wait_for_owner(page,finish,Event())
    assert page.pumps==1

def test_timeout_is_distinct_from_cancellation(monkeypatch):
    m=manager()
    monkeypatch.setattr(cw,"monotonic",iter([0,901]).__next__)
    with pytest.raises(cw._StopWithoutSaving,match="WAIT_TIMEOUT"):
        m._wait_for_owner(Page(Event()),Event(),Event())

def test_cancel_is_distinct():
    cancel=Event()
    cancel.set()
    with pytest.raises(cw._StopWithoutSaving,match="OWNER_CANCELLED"):
        manager()._wait_for_owner(Page(Event()),Event(),cancel)

def test_window_closed_reason():
    page=Page(Event())
    page.closed=True
    with pytest.raises(cw._StopWithoutSaving,match="BROWSER_CLOSED"):
        manager()._wait_for_owner(page,Event(),Event())

@pytest.mark.parametrize("status,reason",[(0,"HTTP_NO_RESPONSE"),(401,"HTTP_401"),
    (403,"HTTP_403"),(429,"HTTP_429"),(500,"HTTP_ERROR")])
def test_http_reason(status,reason):
    with pytest.raises(cw._StopWithoutSaving,match=reason):
        cw.OwnerLoginHandoff._check_http(status)

def test_status_never_serializes_url_query_or_credentials():
    m=manager()
    m._record_navigation(403,"https://user:password@crowdworks.jp/login?token=SECRET")
    state=m.status()
    assert state["navigation_http"]==403
    assert state["navigation_url_allowed"] is False
    assert "SECRET" not in json.dumps(state)
    assert state["login_verified"] is False

def test_unknown_stop_reason_cannot_leak():
    assert str(cw._StopWithoutSaving("secret-password"))=="UNSPECIFIED"


def test_finish_at_expired_deadline_cannot_save(monkeypatch):
    finish = Event()
    finish.set()
    monkeypatch.setattr(cw, "monotonic", iter([0, 901]).__next__)
    with pytest.raises(cw._StopWithoutSaving, match="WAIT_TIMEOUT"):
        manager()._wait_for_owner(Page(finish), finish, Event())


def test_browser_closed_during_dispatch_has_fixed_reason():
    page = Page(Event())
    def close_during_wait(milliseconds):
        page.closed = True
        raise RuntimeError("private exception text")
    page.wait_for_timeout = close_during_wait
    with pytest.raises(cw._StopWithoutSaving, match="BROWSER_CLOSED"):
        manager()._wait_for_owner(page, Event(), Event())
