"""Private forwarding regression: nonce remains the authorization boundary."""
import pytest
from fastapi.testclient import TestClient
import cloud_api

@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", "sample")
    monkeypatch.setattr(cloud_api, "owner_diagnose", lambda: {"status":"STOPPED", "can_start":True})
    calls=[]
    monkeypatch.setattr(cloud_api, "start_owner_desktop", lambda: calls.append(1) or {"status":"STARTING"})
    with TestClient(cloud_api.app) as client:
        yield client, calls

@pytest.mark.parametrize("origin,site,forwarded,good_nonce,expected", [
    ("https://sample-8000.app.github.dev", "same-origin", "", True, 200),
    ("http://localhost:8000", "same-origin", "sample-8000.app.github.dev", True, 200),
    ("http://localhost:8000", "same-origin", "sample-8000.app.github.dev", False, 403),
    ("http://localhost:8000", "cross-site", "sample-8000.app.github.dev", True, 403),
    ("http://localhost:8000", "same-site", "sample-8000.app.github.dev", True, 403),
    ("http://localhost:8000", "", "sample-8000.app.github.dev", True, 403),
    ("http://localhost:8000", "same-origin", "other-8000.app.github.dev", True, 403),
    ("http://localhost:8000", "same-origin", "", True, 403),
    ("https://evil.example", "same-origin", "sample-8000.app.github.dev", True, 403),
    ("https://other-8000.app.github.dev", "same-origin", "", True, 403),
    ("http://localhost:8002", "same-origin", "sample-8000.app.github.dev", True, 403),
    ("http://[malformed", "same-origin", "", True, 403),
])
def test_proxy_matrix(owner,origin,site,forwarded,good_nonce,expected):
    client,calls=owner
    nonce=client.get("/api/owner/diagnose").json()["start_nonce"]
    r=client.post("/api/owner/start",json={"nonce":nonce if good_nonce else "x"*43}, headers={"origin":origin,"sec-fetch-site":site,"x-forwarded-host":forwarded})
    assert r.status_code==expected
    assert len(calls)==(expected==200)
    assert nonce not in r.text
    if expected==403: assert r.json()["source"]=="minifish-owner"

def test_restart_stale_nonce_and_missing_environment(owner,monkeypatch):
    client,calls=owner
    nonce=client.get("/api/owner/diagnose").json()["start_nonce"]
    monkeypatch.setattr(cloud_api,"_OWNER_START_NONCE","n"*43)
    r=client.post("/api/owner/start",json={"nonce":nonce})
    assert r.json()["detail"]=="OWNER_START_PROOF_REQUIRED"
    monkeypatch.delenv("CODESPACE_NAME")
    r=client.post("/api/owner/start",json={"nonce":"n"*43})
    assert r.json()["detail"]=="PRIVATE_CODESPACE_REQUIRED"
    assert not calls

def test_non_json_rejected(owner):
    client,calls=owner
    nonce=client.get("/api/owner/diagnose").json()["start_nonce"]
    r=client.post("/api/owner/start",content='{"nonce":"'+nonce+'"}')
    assert r.status_code in (403, 422)
    if r.status_code == 403: assert r.json()["detail"]=="OWNER_JSON_REQUIRED"
    assert not calls
