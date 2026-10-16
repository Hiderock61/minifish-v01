"""Cross-PR compatibility: encrypted chat article + encrypted mock session.

No real login, private note article, GitHub Issue, note.com write, or paid API.
"""
import json

from cryptography.fernet import Fernet
from minifish.chat_handoff import make_keypair, seal_article, receive_article
from minifish.note_conveyor import Article, run_live
from minifish.session_vault import EncryptedSessionVault


ARTICLE = {
    "title": "MiniFish仮記事（架空）",
    "body": "これは架空の文章。\\n公開・投稿はしない。",
    "series": "架空の試験", "destinations": ["note"],
    "visibility": "draft",
}


def test_private_handoff_and_session_vault_do_not_conflict(tmp_path):
    """Separate article key and cookie key; both remain private."""
    private = tmp_path / "handoff" / "private.pem"
    public = tmp_path / "handoff" / "public.pem"
    make_keypair(private, public)
    payload = seal_article(ARTICLE, public.read_bytes())
    inbox = tmp_path / "inbox"
    report = receive_article(payload, private, inbox)
    assert report["status"] == "ARTICLE_RECEIVED_NOT_POSTED"
    article = Article.from_dict(json.loads((inbox / (report["content_key"] + ".json")).read_text()))
    assert article.title == ARTICLE["title"]
    assert article.body == ARTICLE["body"]
    cookie_key = Fernet.generate_key()
    vault = EncryptedSessionVault(tmp_path / "vault" / "mock.vault", cookie_key)
    vault.save({"cookies": [], "origins": []})
    assert vault.load() == {"cookies": [], "origins": []}
    assert ARTICLE["title"].encode() not in vault.path.read_bytes()
    assert ARTICLE["body"].encode() not in vault.path.read_bytes()
    assert report["external_writes"] == 0 and report["paid_calls"] == 0


def test_note_live_does_not_trust_legacy_plaintext_login(tmp_path, monkeypatch):
    """A mock legacy file cannot grant authentication or cause note.com access."""
    root = tmp_path / "sites"
    legacy = root / "note_jp" / "storage.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
    config = tmp_path / "auth_sites.json"
    config.write_text(json.dumps({"sites": [{
        "site_id": "note_jp", "base_url": "https://note.com",
        "check_url": "https://note.com/account", "success_selector": "#signed-in",
        "login_path_markers": ["/login"],
        "allow_actions": ["goto", "fill", "click", "back", "wait"]
    }]}), encoding="utf-8")
    selectors = tmp_path / "selectors.json"
    selectors.write_text(json.dumps({
        "editor_url": "https://note.com/new",
        "title": "#title", "body": "#body", "save": "#draft",
        "saved_proof": "#saved", "save_label": "下書き保存"
    }), encoding="utf-8")
    monkeypatch.delenv("MINIFISH_NOTE_SESSION_KEY", raising=False)
    res = run_live(Article.from_dict(ARTICLE), config=config,
                   selectors_path=selectors, state_root=root)
    assert res["status"] == "AUTH_REQUIRED"
    assert legacy.read_text() == '{"cookies":[],"origins":[]}'
    assert not (root / "note_jp" / "storage.vault").exists()


def test_note_missing_key_blocks_even_with_vault_file(tmp_path, monkeypatch):
    root = tmp_path / "sites"
    path = root / "note_jp" / "storage.vault"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a real vault")
    config = tmp_path / "auth_sites.json"
    config.write_text(json.dumps({"sites": [{
        "site_id": "note_jp", "base_url": "https://note.com",
        "check_url": "https://note.com/account", "success_selector": "#signed-in"
    }]}), encoding="utf-8")
    selectors = tmp_path / "selectors.json"
    selectors.write_text(json.dumps({
        "editor_url": "https://note.com/new", "title": "#title",
        "body": "#body", "save": "#draft",
        "saved_proof": "#saved", "save_label": "下書き保存"
    }), encoding="utf-8")
    monkeypatch.delenv("MINIFISH_NOTE_SESSION_KEY", raising=False)
    res = run_live(Article.from_dict(ARTICLE), config=config,
                   selectors_path=selectors, state_root=root)
    assert res["status"] == "AUTH_REQUIRED"
