import time
from threading import Event
import pytest
from fastapi.testclient import TestClient
import g1b_mock_app as app
from minifish import crowdworks_handoff as cw
from test_crowdworks_handoff import FakeBrowser, FakeVault, _wait_state

def test_finish_after_completed_save_is_idempotent():
    manager=cw.OwnerLoginHandoff()
    manager._status="SESSION_SAVED_LOGIN_UNVERIFIED"
    manager.finish()
    manager.finish()
    assert manager.status()["status"]=="SESSION_SAVED_LOGIN_UNVERIFIED"

def test_finish_while_saving_is_idempotent():
    manager=cw.OwnerLoginHandoff()
    manager._status="SAVING_SESSION"
    manager.finish()
    assert manager.status()["status"]=="SAVING_SESSION"

@pytest.mark.parametrize("state",["LOGIN_NOT_STARTED","STOPPED_NO_AUTH_ASSERTION",
                                  "BLOCKED_SESSION_SAVE"])
def test_invalid_finish_still_rejected(state):
    manager=cw.OwnerLoginHandoff()
    manager._status=state
    with pytest.raises(ValueError):
        manager.finish()

def test_http_duplicate_finish_saves_once(monkeypatch):
    fake=FakeVault()
    monkeypatch.setenv("CODESPACE_NAME","test-private")
    monkeypatch.setattr(cw,"_secret_vault",lambda:fake)
    monkeypatch.setattr(cw,"PlaywrightBrowser",FakeBrowser)
    manager=cw.OwnerLoginHandoff()
    monkeypatch.setattr(app,"real_handoff",manager)
    manager.launch()
    _wait_state(manager,{"WAITING_FOR_HUMAN"})
    FakeBrowser.entered[-1].page.url=cw.HOME_URL
    client=TestClient(app.app)
    nonce=client.get("/g1/owner/status").json()["action_nonce"]
    assert client.post("/g1/owner/finish",json={"nonce":nonce}).status_code==200
    _wait_state(manager,{"SESSION_SAVED_LOGIN_UNVERIFIED"})
    assert client.post("/g1/owner/finish",json={"nonce":nonce}).status_code==200
    assert fake.count==1

def test_restore_remains_open_without_resaving(monkeypatch):
    fake=FakeVault()
    fake.saved=True
    monkeypatch.setenv("CODESPACE_NAME","test-private")
    monkeypatch.setattr(cw,"_secret_vault",lambda:fake)
    monkeypatch.setattr(cw,"PlaywrightBrowser",FakeBrowser)
    manager=cw.OwnerLoginHandoff()
    manager.launch(check_saved=True)
    state=_wait_state(manager,{"SESSION_REOPENED_LOGIN_NOT_VERIFIED"})
    assert state["busy"]
    assert fake.count==0
    manager.cancel()
    _wait_state(manager,{"STOPPED_NO_AUTH_ASSERTION"})
    assert fake.count==0

def test_ui_save_pending_and_success_are_explicit():
    html=app.REAL_LOGIN_HTML
    assert "if(ownerActionPending)return" in html
    assert 'ownerActionPending=false' in html
    assert "暗号化保存が完了" in html
    assert 'd.status==="SAVING_SESSION"' in html
