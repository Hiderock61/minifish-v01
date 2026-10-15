"""Offline acceptance tests: plaintext never leaves the private receiver."""
import json
import os
from pathlib import Path
import pytest

import bridge_worker
from minifish.chat_handoff import (
    make_keypair, seal_article, open_article, receive_article,
)

FIXTURE = {
    "title": "チャットから魚へ｜試験",
    "body": "これは公開しても問題のない架空の疎通試験文です。\n投稿はしません。",
    "series": "架空試験", "source": "chatgpt",
    "tags": ["試験"], "destinations": ["note"], "visibility": "draft",
}


def _keys(tmp_path: Path):
    private = tmp_path / "secret.pem"
    public = tmp_path / "public.pem"
    make_keypair(private, public)
    return private, public


def test_sealed_handoff_preserves_original_and_hides_plaintext(tmp_path):
    private, public = _keys(tmp_path)
    envelope = seal_article(FIXTURE, public.read_bytes())
    public_body = json.dumps({"mode": "encrypted_article", "envelope": envelope},
                             ensure_ascii=False)
    assert FIXTURE["title"] not in public_body
    assert FIXTURE["body"] not in public_body
    article = open_article(envelope, private.read_bytes())
    assert article.title == FIXTURE["title"]
    assert article.body == FIXTURE["body"]
    assert article.manifest()["visibility"] == "draft"


def test_private_inbox_receives_once_without_browser_or_publish(tmp_path, monkeypatch):
    private, public = _keys(tmp_path)
    envelope = seal_article(FIXTURE, public.read_bytes())
    inbox = tmp_path / "private_inbox"
    result = receive_article(envelope, private, inbox)
    assert result["status"] == "ARTICLE_RECEIVED_NOT_POSTED"
    assert result["external_writes"] == 0
    assert result["paid_calls"] == 0
    assert "title" not in result and "body" not in result
    p = inbox / (result["content_key"] + ".json")
    assert json.loads(p.read_text(encoding="utf-8"))["body"] == FIXTURE["body"]
    assert p.stat().st_mode & 0o077 == 0
    again = receive_article(envelope, private, inbox)
    assert again["status"] == "ALREADY_RECEIVED"


def test_tampered_ciphertext_is_rejected(tmp_path):
    private, public = _keys(tmp_path)
    envelope = seal_article(FIXTURE, public.read_bytes())
    encrypted = envelope["ciphertext"]
    envelope["ciphertext"] = ("A" if encrypted[0] != "A" else "B") + encrypted[1:]
    with pytest.raises(ValueError, match="DECRYPTION_FAILED"):
        open_article(envelope, private.read_bytes())


def test_wrong_recipient_cannot_decrypt(tmp_path):
    private, public = _keys(tmp_path)
    other, _ = _keys(tmp_path / "other")
    envelope = seal_article(FIXTURE, public.read_bytes())
    with pytest.raises(ValueError, match="DECRYPTION_FAILED"):
        open_article(envelope, other.read_bytes())


def test_bad_or_unsafe_article_is_blocked_before_encryption(tmp_path):
    _, public = _keys(tmp_path)
    for change in ({"visibility": "public"}, {"destinations": ["stranger"]},
                   {"body": "x" * 40000}):
        with pytest.raises(ValueError):
            seal_article({**FIXTURE, **change}, public.read_bytes())


def test_keys_are_not_overwritten(tmp_path):
    private, public = _keys(tmp_path)
    original = private.read_bytes()
    with pytest.raises(FileExistsError):
        make_keypair(private, public)
    assert private.read_bytes() == original


def test_missing_private_key_stops_without_public_write(tmp_path):
    result = receive_article({"version": 1}, tmp_path / "missing.pem", tmp_path / "inbox")
    assert result["status"] == "AUTH_SETUP_REQUIRED"
    assert result["external_writes"] == 0


def test_bridge_accepts_only_owner_job_and_returns_safe_status(tmp_path, monkeypatch):
    private, public = _keys(tmp_path)
    from minifish import chat_handoff
    monkeypatch.setattr(chat_handoff, "PRIVATE_KEY_PATH", private)
    monkeypatch.setattr(chat_handoff, "INBOX_PATH", tmp_path / "inbox")
    # Defaults are bound at definition time, so override the call instead.
    original = chat_handoff.receive_article
    def receive(envelope):
        return original(envelope, private, tmp_path / "inbox")
    monkeypatch.setattr(chat_handoff, "receive_article", receive)
    body = json.dumps({
        "mode": "encrypted_article",
        "envelope": seal_article(FIXTURE, public.read_bytes())
    })
    job = {
        "number": 100, "title": "[MINIFISH JOB] Encrypted note intake",
        "author": {"login": bridge_worker.OWNER}, "body": body,
    }
    result = bridge_worker.run_job(job)
    assert result["status"] == "ARTICLE_RECEIVED_NOT_POSTED"
    with pytest.raises(ValueError, match="UNAUTHORIZED"):
        bridge_worker.run_job({**job, "author": {"login": "other"}})
    with pytest.raises(ValueError, match="UNAUTHORIZED"):
        bridge_worker.run_job({**job, "title": "untrusted issue"})
