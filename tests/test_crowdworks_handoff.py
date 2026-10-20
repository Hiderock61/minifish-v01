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

def test_real_private_page_survives_proxy_host_rewrite(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    monkeypatch.setenv("CODESPACE_NAME", "glorious-disco-example")
    for forwarded_host in ("127.0.0.1:8002", "localhost:8002",
                           "codespace-internal:8002",
                           "glorious-disco-example-8002.app.github.dev"):
        request = Request({
            "type": "http", "method": "GET", "scheme": "https",
            "path": "/login-ready", "headers": [(b"host", forwarded_host.encode())],
        })
        result = g1b_mock_app.live_login_page(request)
        assert result.status_code == 200
        assert b"G1_OWNER_8002_NONCE_PROXY_20261021" in result.body
        assert result.headers["x-frame-options"] == "DENY"
    monkeypatch.delenv("CODESPACE_NAME")
    with pytest.raises(HTTPException):
        g1b_mock_app.live_login_page(request)


def test_real_owner_post_allows_codespace_origin_despite_forwarded_host(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    monkeypatch.setenv("CODESPACE_NAME", "glorious-disco-example")
    good = "https://glorious-disco-example-8002.app.github.dev"
    def req(host, origin, fetch_site="same-origin", marker="G1B"):
        return Request({
            "type": "http", "method": "POST", "path": "/g1/owner/open",
            "scheme": "https", "headers": [
                (b"host", host.encode()), (b"origin", origin.encode()),
                (b"x-minifish-mock-action", marker.encode()),
                (b"sec-fetch-site", fetch_site.encode()),
            ],
        })
    for host in ("localhost:8002", "127.0.0.1:8002",
                 "codespace-internal:8002",
                 "glorious-disco-example-8002.app.github.dev"):
        g1b_mock_app.require_same_origin(req(host, good))
    for request in (
        req("localhost:8002", "https://evil.example"),
        req("localhost:8002", good, "cross-site"),
        req("localhost:8002", good, "same-origin", "WRONG"),
        req("localhost:8002", "https://different-8002.app.github.dev"),
    ):
        with pytest.raises(HTTPException) as blocked:
            g1b_mock_app.require_same_origin(request)
        assert blocked.value.status_code == 403

def test_real_owner_button_changes_state_via_private_proxy(monkeypatch):
    """Actual HTTP route: GET status -> POST open -> status changes, no real website."""
    from fastapi.testclient import TestClient
    class FakeHandoff:
        def __init__(self):
            self.current="LOGIN_NOT_STARTED"
            self.calls=[]
        def status(self):
            return {"status":self.current,"busy":False}
        def launch(self,check_saved=False):
            self.calls.append("open")
            self.current="OPENING_PRIVATE_BROWSER"
        def finish(self): self.calls.append("finish")
        def cancel(self): self.calls.append("stop")
    handoff=FakeHandoff()
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco-test")
    monkeypatch.setattr(g1b_mock_app,"real_handoff",handoff)
    origin="https://glorious-disco-test-8002.app.github.dev"
    client=TestClient(g1b_mock_app.app,base_url=origin)
    page=client.get("/login-ready")
    assert page.status_code==200
    assert b'id="actionResult"' in page.content
    assert b"JSON.stringify({nonce:ownerActionNonce})" in page.content
    state=client.get("/g1/owner/status")
    assert state.status_code==200
    assert state.json()["status"]=="LOGIN_NOT_STARTED"
    nonce=state.json()["action_nonce"]
    assert len(nonce)>=40 and nonce.encode() not in page.content
    headers={"host":"127.0.0.1:8002","origin":origin,
             "sec-fetch-site":"same-origin","x-minifish-mock-action":"G1B"}
    invalid=client.post("/g1/owner/open",json={"nonce":"invalid"},headers=headers)
    assert invalid.status_code in (403,422) and handoff.calls==[]
    success=client.post("/g1/owner/open",json={"nonce":nonce},headers=headers)
    assert success.status_code==200
    assert success.json()["status"]=="OPENING_PRIVATE_BROWSER"
    assert client.get("/g1/owner/status").json()["status"]=="OPENING_PRIVATE_BROWSER"
    assert handoff.calls==["open"]


def test_real_owner_nonce_rejects_cross_site_and_bad_content(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco-test")
    origin="https://glorious-disco-test-8002.app.github.dev"
    client=TestClient(g1b_mock_app.app,base_url=origin)
    nonce=client.get("/g1/owner/status").json()["action_nonce"]
    base={"x-minifish-mock-action":"G1B","host":"localhost:8002"}
    for hdr in (
        {"origin":"https://evil.example","sec-fetch-site":"cross-site"},
        {"origin":origin,"sec-fetch-site":"cross-site"},
        {"origin":"https://something.example","sec-fetch-site":"cross-site"},
    ):
        r=client.post("/g1/owner/open",json={"nonce":nonce},headers={**base,**hdr})
        assert r.status_code==403
    assert client.post("/g1/owner/open",headers={**base,"origin":origin}).status_code in (403,422)
    assert client.post("/g1/owner/open",data={"nonce":nonce},
                       headers={**base,"origin":origin}).status_code in (403,422)
    class Fake:
        def status(self): return {"status":"LOGIN_NOT_STARTED","busy":False}
        def launch(self,check_saved=False): pass
    monkeypatch.setattr(g1b_mock_app,"real_handoff",Fake())
    # Proxy with missing Origin: correctly issued nonce is sufficient.
    assert client.post("/g1/owner/open",json={"nonce":nonce},headers=base).status_code==200


def test_owner_vnc_password_view_uses_proof(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco-test")
    monkeypatch.setenv("HOME",str(tmp_path))
    origin="https://glorious-disco-test-8002.app.github.dev"
    client=TestClient(g1b_mock_app.app,base_url=origin)
    nonce=client.get("/g1/owner/status").json()["action_nonce"]
    passwd=g1b_mock_app.private_root()/"vnc-password.txt"
    passwd.write_text("Sample12",encoding="ascii")
    passwd.chmod(0o600)
    headers={"x-minifish-mock-action":"G1B","origin":origin}
    assert client.post("/g1/owner/vnc-password",json={"nonce":"invalid"},headers=headers).status_code in (403,422)
    result=client.post("/g1/owner/vnc-password",json={"nonce":nonce},headers=headers)
    assert result.status_code==200
    assert result.json()["password"]=="Sample12"
    assert "no-store" in result.headers["cache-control"]


def test_login_page_keeps_request_error_after_status_poll():
    html=g1b_mock_app.REAL_LOGIN_HTML
    assert 'id="actionResult"' in html
    assert "actionResult.textContent" in html
    assert "操作は受理されませんでした（HTTP " in html
    assert '"/g1/owner/vnc-password"' in html
    assert "body:JSON.stringify({nonce:ownerActionNonce})" in html
    assert g1b_mock_app._OWNER_ACTION_NONCE not in html

def test_private_proxy_preflight_matches_owner_start_without_launch(monkeypatch):
    """Same JSON POST security path, from real browser Host, no web launch."""
    from fastapi.testclient import TestClient
    class SafeHandoff:
        def __init__(self): self.launch_count=0
        def status(self): return {"status":"LOGIN_NOT_STARTED","busy":False}
        def launch(self,check_saved=False): self.launch_count+=1
    fake=SafeHandoff()
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco-real")
    monkeypatch.setattr(g1b_mock_app,"real_handoff",fake)
    browser_origin="https://glorious-disco-real-8002.app.github.dev"
    client=TestClient(g1b_mock_app.app,base_url=browser_origin)
    token=client.get("/g1/owner/status").json()["action_nonce"]
    for headers in (
        {"host":"localhost:8002","origin":browser_origin,
         "sec-fetch-site":"same-origin"},
        {"host":"127.0.0.1:8002","origin":browser_origin},
        {"host":"upstream.local:8002"},
        {"host":"glorious-disco-real-8002.app.github.dev",
         "origin":browser_origin},
    ):
        result=client.post("/g1/owner/probe",json={"nonce":token},headers=headers)
        assert result.status_code==200
        assert result.json()["status"]=="OWNER_ACTION_PROXY_READY"
    assert fake.launch_count==0
    assert client.get("/g1/owner/status").json()["status"]=="LOGIN_NOT_STARTED"
    # Invalid nonce or browser-identified cross-site request never passes.
    assert client.post("/g1/owner/probe",json={"nonce":"wrong"},
        headers={"origin":browser_origin}).status_code in (403,422)
    assert client.post("/g1/owner/probe",json={"nonce":token},
        headers={"origin":"https://evil.example","sec-fetch-site":"cross-site"}).status_code==403
    assert client.post("/g1/owner/probe",json={"nonce":token},
        headers={"origin":browser_origin,"sec-fetch-site":"cross-site"}).status_code==403


def test_browser_preflight_disables_real_buttons_before_proxy_pass():
    html=g1b_mock_app.REAL_LOGIN_HTML
    assert '"/g1/owner/probe"' in html
    assert 'ownerProbeState==="PASS"' in html
    assert 'document.getElementById("open").disabled=d.busy||!verified' in html
    assert "自動通信検査で停止：" in html
    assert "UPSTREAM_OR_UNKNOWN_" in html
    assert "操作停止：自動通信検査を通過していません。" in html


def test_live_origin_rewrite_no_longer_blocks_private_nonce(monkeypatch):
    """Previously OWNER_CROSS_ORIGIN_REJECTED; exact same proxy preflight now 200.

    The private nonce and browser fetch-site boundary remain required.
    """
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESPACE_NAME", "glorious-disco-real")
    origin = "https://glorious-disco-real-8002.app.github.dev"
    client = TestClient(g1b_mock_app.app, base_url=origin)
    nonce = client.get("/g1/owner/status").json()["action_nonce"]
    for proxy_origin in (
        "https://github-port-relay.invalid",
        "https://glorious-disco-real-8002.app.github.dev:443",
        "null",
    ):
        reply = client.post("/g1/owner/probe", json={"nonce": nonce}, headers={
            "host": "127.0.0.1:8002", "origin": proxy_origin,
            "sec-fetch-site": "same-origin",
        })
        assert reply.status_code == 200
        assert reply.json()["status"] == "OWNER_ACTION_PROXY_READY"
        assert "access-control-allow-origin" not in reply.headers
        # Possession of a rewritten Origin does NOT bypass proof or fetch-site.
        denied = client.post("/g1/owner/probe", json={"nonce":"invalid"}, headers={
            "origin":proxy_origin, "sec-fetch-site":"same-origin",
        })
        assert denied.status_code in (403,422)
        denied = client.post("/g1/owner/probe", json={"nonce":nonce}, headers={
            "origin":proxy_origin, "sec-fetch-site":"cross-site",
        })
        assert denied.status_code == 403


def test_owner_build_fingerprint_is_fixed_at_server_import(monkeypatch):
    """Never leak a token and never confuse the running code with updated disk."""
    import hashlib
    from pathlib import Path
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESPACE_NAME","glorious-disco-fingerprint")
    app=g1b_mock_app.app
    response=TestClient(app).get("/g1/owner/build")
    assert response.status_code==200
    assert response.json() == {
        "source_sha256":hashlib.sha256(Path(g1b_mock_app.__file__).read_bytes()).hexdigest()
    }
    assert "access-control-allow-origin" not in response.headers
    assert "no-store" in response.headers["cache-control"]
