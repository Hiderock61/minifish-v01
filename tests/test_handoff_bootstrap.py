"""Safe, idempotent one-time Codespace recipient setup (synthetic only)."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from cryptography.hazmat.primitives import serialization

from minifish.chat_handoff import bootstrap_receiver, seal_article, receive_article


def _setup(tmp_path, monkeypatch, announce):
    monkeypatch.setenv("CODESPACES", "true")
    private = tmp_path / "receiver" / "private.pem"
    public = tmp_path / "receiver" / "public.pem"
    receipt = tmp_path / "receiver" / "receipt.json"
    result = bootstrap_receiver(private_path=private, public_path=public,
                                receipt_path=receipt, publish_comment=announce)
    return result, private, public, receipt


def test_bootstrap_blocked_outside_codespaces(tmp_path, monkeypatch):
    monkeypatch.delenv("CODESPACES", raising=False)
    messages = []
    res, private, public, receipt = _setup_no_env(tmp_path, messages.append)
    assert res["status"] == "BLOCKED_NOT_CODESPACES"
    assert not private.exists() and not public.exists() and not receipt.exists()
    assert not messages


def _setup_no_env(tmp_path, announce):
    private = tmp_path / "receiver" / "private.pem"
    public = tmp_path / "receiver" / "public.pem"
    receipt = tmp_path / "receiver" / "receipt.json"
    res = bootstrap_receiver(private_path=private, public_path=public,
                             receipt_path=receipt, publish_comment=announce)
    return res, private, public, receipt


def test_codespace_bootstrap_announces_only_public_once(tmp_path, monkeypatch):
    published = []
    res, private, public, receipt = _setup(tmp_path, monkeypatch, published.append)
    assert res["status"] == "PUBLIC_KEY_ANNOUNCED"
    assert len(published) == 1
    assert "MINIFISH_HANDOFF_PUBLIC_KEY v1" in published[0]
    assert "-----BEGIN PUBLIC KEY-----" in published[0]
    assert "\\n" not in published[0]
    assert "PRIVATE KEY" not in published[0]
    assert private.read_text() not in published[0]
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert json.loads(receipt.read_text())["fingerprint"] == res["fingerprint"]
    again = bootstrap_receiver(private_path=private, public_path=public,
                               receipt_path=receipt, publish_comment=published.append)
    assert again["status"] == "PUBLIC_KEY_ALREADY_ANNOUNCED"
    assert len(published) == 1


def test_an_article_can_be_encrypted_with_announced_pubkey(tmp_path, monkeypatch):
    published = []
    res, private, public, receipt = _setup(tmp_path, monkeypatch, published.append)
    assert res["status"] == "PUBLIC_KEY_ANNOUNCED"
    article = {
        "title": "架空のMiniFish配送試験",
        "body": "公開しても問題ない試験文。投稿はしません。",
        "destinations": ["note"], "visibility": "draft"
    }
    envelope = seal_article(article, public.read_bytes())
    assert article["body"] not in json.dumps(envelope, ensure_ascii=False)
    inbox = tmp_path / "receiver" / "inbox"
    received = receive_article(envelope, private, inbox)
    assert received["status"] == "ARTICLE_RECEIVED_NOT_POSTED"
    delivered = json.loads((inbox / (received["content_key"] + ".json")).read_text())
    assert delivered["body"] == article["body"]


def test_receipt_mismatch_and_untrusted_paths_block_safely(tmp_path, monkeypatch):
    msgs = []
    _, private, public, receipt = _setup(tmp_path, monkeypatch, msgs.append)
    receipt.write_text(json.dumps({"fingerprint": "old-key"}))
    outcome = bootstrap_receiver(private_path=private, public_path=public,
                                 receipt_path=receipt, publish_comment=msgs.append)
    assert outcome["status"] == "BLOCKED_RECEIPT_MISMATCH"
    assert len(msgs) == 1
    receipt.unlink()
    private.chmod(0o644)
    outcome = bootstrap_receiver(private_path=private, public_path=public,
                                 receipt_path=receipt, publish_comment=msgs.append)
    assert outcome["status"] == "BLOCKED_UNSAFE_PRIVATE_KEY_PERMISSIONS"
    assert len(msgs) == 1
