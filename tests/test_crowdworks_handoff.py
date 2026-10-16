"""G1 real-site login handoff: no automated credentials, STOP and no saved token on failure."""
import os
import time
from threading import Event

import pytest

import g1b_mock_app
from minifish import crowdworks_handoff as cw


@pytest.mark.parametrize("url,expected", [
    ("https://crowdworks.jp/login", True),
    ("https://crowdworks.jp/", True),
    ("https://www.crowdworks.jp/help", True),
    ("https://accounts.google.com/", False),
    ("http://crowdworks.jp/login", False),
    ("https://crowdworks.jp.evil.example/login", False),
    ("https://evil.example@crowdworks.jp/login", False),
    ("file:///etc/passwd", False),
    ("https://crowdworks.jp:8443/login", False),
    ("https://coconala.com/login", False),
    ("https://note.com/login", False),
])
def test_exact_owner_site_navigation_policy(url,expected):
    assert cw._approved_url(url) is expected


class DummyRoute:
    def __init__(self, url, navigation=True):
        page = object()
        frame = type("Frame",(),{"page":type("Page",(),{"main_frame":object()})()})()
        if navigation:
            frame.page.main_frame = frame
        self.request = type("Req", (), {
            "url":url, "frame":frame,
            "is_navigation_request":lambda self: navigation
        })()
        self.decision = None
    def continue_(self): self.decision = "PASS"
    def abort(self): self.decision = "STOP"


def test_navigation_boundary_never_opens_other_service():
    for url in ("https://coconala.com/login", "https://accounts.google.com/"):
        route = DummyRoute(url)
        cw._browser_route(route)
        assert route.decision == "STOP"
    route = DummyRoute(cw.LOGIN_URL)
    cw._browser_route(route)
    assert route.decision == "PASS"


def _wait_state(manager,allowed,seconds=3):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        val=manager.status()
        if val["status"] in allowed and not val["busy"] if val["status"] not in ("WAITING_FOR_HUMAN",) else val["status"] in allowed:
            return val
        time.sleep(.02)
    raise AssertionError("G1_OWNER_STATE_TIMEOUT:"+str(manager.status()))


class FakeVault:
    def __init__(self):
        self.saved=False
        self.count=0
    def load(self):
        return {"cookies":[],"origins":[]} if self.saved else None


class FakeBrowser:
    entered=[]
    class Page:
        def __init__(self):
            self.url = "about:blank"
        def goto(self,url,**kwargs):
            self.url=url
            return type("Resp",(),{"status":200})()
    class Context:
        def route(self,*args): pass
    def __init__(self,*,session_vault=None,**kwargs):
        assert kwargs["profile_path"] is None
        assert kwargs["capture_dir"] is None
        self.session_vault=session_vault
        self.page=self.Page()
        self.context=self.Context()
        self.entered.append(self)
    def __enter__(self): return self
    @property
    def current_url(self): return self.page.url
    def __exit__(self,exctype,*args):
        if exctype is None:
            self.session_vault.saved=True
            self.session_vault.count+=1


def test_user_manually_finishes_save_without_auto_login(monkeypatch):
    fake=FakeVault()
    FakeBrowser.entered.clear()
    monkeypatch.setenv("CODESPACE_NAME","test-private")
    monkeypatch.setattr(cw,"_secret_vault",lambda:fake)
    monkeypatch.setattr(cw,"PlaywrightBrowser",FakeBrowser)
    manager=cw.OwnerLoginHandoff()
    manager.launch()
    assert _wait_state(manager,{"WAITING_FOR_HUMAN"})["login_verified"] is False
    assert fake.count==0
    assert FakeBrowser.entered[-1].page.url==cw.LOGIN_URL
    # Simulate user manually completing login; MiniFish does not fill fields.
    FakeBrowser.entered[-1].page.url=cw.HOME_URL
    manager.finish()
    assert _wait_state(manager,{"SESSION_SAVED_LOGIN_UNVERIFIED"})["status"]=="SESSION_SAVED_LOGIN_UNVERIFIED"
    assert fake.count==1
    manager.launch(check_saved=True)
    assert _wait_state(manager,{"SESSION_REOPENED_LOGIN_NOT_VERIFIED"})["status"]=="SESSION_REOPENED_LOGIN_NOT_VERIFIED"
    assert fake.count==2


def test_stop_does_not_save_session(monkeypatch):
    fake=FakeVault()
    monkeypatch.setenv("CODESPACE_NAME","test-private")
    monkeypatch.setattr(cw,"_secret_vault",lambda:fake)
    monkeypatch.setattr(cw,"PlaywrightBrowser",FakeBrowser)
    manager=cw.OwnerLoginHandoff()
    manager.launch()
    _wait_state(manager,{"WAITING_FOR_HUMAN"})
    manager.cancel()
    assert _wait_state(manager,{"STOPPED_NO_AUTH_ASSERTION"})["status"]=="STOPPED_NO_AUTH_ASSERTION"
    assert fake.count==0


def test_login_form_alone_is_not_saved_as_success(monkeypatch):
    fake=FakeVault()
    monkeypatch.setenv("CODESPACE_NAME","test-private")
    monkeypatch.setattr(cw,"_secret_vault",lambda:fake)
    monkeypatch.setattr(cw,"PlaywrightBrowser",FakeBrowser)
    manager=cw.OwnerLoginHandoff()
    manager.launch()
    _wait_state(manager,{"WAITING_FOR_HUMAN"})
    manager.finish()
    assert _wait_state(manager,{"STOPPED_NO_AUTH_ASSERTION"})["status"]=="STOPPED_NO_AUTH_ASSERTION"
    assert fake.count==0


def test_owner_login_no_remote_mode(monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME",raising=False)
    m=cw.OwnerLoginHandoff()
    with pytest.raises(ValueError,match="PRIVATE_CODESPACE_REQUIRED"):
        m.launch()
    assert m.status()["status"]=="LOGIN_NOT_STARTED"


def test_private_login_page_does_not_expose_credentials(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    page=g1b_mock_app.REAL_LOGIN_HTML
    assert "ログイン画面を開く" in page
    assert "8002" in page and "6081" in page
    assert "クラウドワークス" in page
    assert "入力" not in page or "ChatGPTへパスワードを貼る必要はありません" in page
    assert "<input type=\"password\"" not in page
    assert "sk-" not in page
    scope={"type":"http","method":"GET","scheme":"https",
           "headers":[(b"host",b"test-8002.app.github.dev")],
           "server":("test-8002.app.github.dev",443),"path":"/login-ready"}
    request=Request(scope)
    monkeypatch.delenv("CODESPACE_NAME",raising=False)
    with pytest.raises(HTTPException) as e:
        g1b_mock_app.live_login_page(request)
    assert e.value.status_code==403
    monkeypatch.setenv("CODESPACE_NAME","test-private")
    assert g1b_mock_app.live_login_page(request).status_code==200
