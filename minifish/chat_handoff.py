"""Encrypted handoff from ChatGPT/GitHub Issue to the PRIVATE MiniFish inbox.

The public issue only contains ciphertext. Private key and decrypted articles
stay under .minifish/ in a persistent Codespace, never in git or Action logs.
This module deliberately NEVER touches note.com or publishes anything.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from hashlib import sha256

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONTEXT = b"MiniFish chat-to-note private intake v1"
PRIVATE_KEY_PATH = Path(".minifish/handoff/recipient_private.pem")
PUBLIC_KEY_PATH = Path(".minifish/handoff/recipient_public.pem")
INBOX_PATH = Path(".minifish/handoff/inbox")
MAX_ARTICLE_BYTES = 38_000


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str, length: int | None = None) -> bytes:
    if not isinstance(value, str) or len(value) > 70_000:
        raise ValueError("INVALID_ENVELOPE")
    try:
        out = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except Exception as exc:
        raise ValueError("INVALID_ENVELOPE") from exc
    if length is not None and len(out) != length:
        raise ValueError("INVALID_ENVELOPE")
    return out


def make_keypair(private_path: Path = PRIVATE_KEY_PATH, public_path: Path = PUBLIC_KEY_PATH) -> None:
    """One-time Codespace setup. Never overwrite a private key."""
    if private_path.exists() or public_path.exists():
        raise FileExistsError("KEYPAIR_ALREADY_EXISTS; refusing to replace keys")
    private_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    public_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = x25519.X25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    )
    public_bytes = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fd = os.open(private_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(private_bytes)
    except BaseException:
        private_path.unlink(missing_ok=True)
        raise
    public_path.write_bytes(public_bytes)


def _derive(secret: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=CONTEXT).derive(secret)


def seal_article(article_data: dict, public_pem: bytes) -> dict:
    """Sender-side method. Never place plaintext in a public GitHub Issue."""
    from .note_conveyor import Article
    article = Article.from_dict(article_data)
    canonical = {
        "title": article.title, "body": article.body, "series": article.series,
        "tags": list(article.tags), "magazine": article.magazine,
        "source": article.source, "destinations": list(article.destinations),
        "visibility": "draft"
    }
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_ARTICLE_BYTES:
        raise ValueError("ARTICLE_TOO_LARGE_FOR_GITHUB_ISSUE")
    pub = serialization.load_pem_public_key(public_pem)
    if not isinstance(pub, x25519.X25519PublicKey):
        raise ValueError("INVALID_RECIPIENT_KEY")
    eph = x25519.X25519PrivateKey.generate()
    nonce = os.urandom(12)
    encrypted = AESGCM(_derive(eph.exchange(pub))).encrypt(nonce, raw, CONTEXT)
    return {
        "version": 1, "kind": "note_draft_private",
        "ephemeral_key": _b64(eph.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
        "nonce": _b64(nonce), "ciphertext": _b64(encrypted)
    }


def open_article(envelope: dict, private_pem: bytes):
    """Codespace receiver. Decrypt and validate strictly; no site writes."""
    from .note_conveyor import Article
    if not isinstance(envelope, dict) or set(envelope) != {
        "version", "kind", "ephemeral_key", "nonce", "ciphertext"
    } or envelope.get("version") != 1 or envelope.get("kind") != "note_draft_private":
        raise ValueError("INVALID_ENVELOPE")
    try:
        private = serialization.load_pem_private_key(private_pem, password=None)
        if not isinstance(private, x25519.X25519PrivateKey):
            raise ValueError("INVALID_RECIPIENT_KEY")
        eph = x25519.X25519PublicKey.from_public_bytes(_unb64(envelope["ephemeral_key"], 32))
        nonce = _unb64(envelope["nonce"], 12)
        ciphertext = _unb64(envelope["ciphertext"])
        if len(ciphertext) > MAX_ARTICLE_BYTES + 16:
            raise ValueError("INVALID_ENVELOPE")
        raw = AESGCM(_derive(private.exchange(eph))).decrypt(nonce, ciphertext, CONTEXT)
        if len(raw) > MAX_ARTICLE_BYTES:
            raise ValueError("INVALID_ENVELOPE")
        obj = json.loads(raw.decode("utf-8"))
        return Article.from_dict(obj)
    except (InvalidTag, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("DECRYPTION_FAILED") from exc


def receive_article(envelope: dict, private_path: Path = PRIVATE_KEY_PATH,
                    inbox_path: Path = INBOX_PATH) -> dict:
    """Persist only in .minifish private inbox. Never run browser or publish."""
    if not private_path.is_file():
        return {"status": "AUTH_SETUP_REQUIRED", "reason": "PRIVATE_HANDOFF_KEY_MISSING",
                "external_writes": 0, "paid_calls": 0}
    article = open_article(envelope, private_path.read_bytes())
    inbox_path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(inbox_path, 0o700)
    target = inbox_path / (article.content_key + ".json")
    if target.exists():
        return {"status": "ALREADY_RECEIVED", "content_key": article.content_key,
                "external_writes": 0, "paid_calls": 0}
    private_package = {
        "title": article.title, "body": article.body, "series": article.series,
        "tags": list(article.tags), "magazine": article.magazine,
        "source": article.source, "destinations": list(article.destinations),
        "visibility": "draft"
    }
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(private_package, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    # No title, content, URLs or private filesystem paths in public reply.
    return {"status": "ARTICLE_RECEIVED_NOT_POSTED",
            "content_key": article.content_key, "external_writes": 0, "paid_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description="Private chat-to-MiniFish envelope")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("keygen")
    init.add_argument("--private", type=Path, default=PRIVATE_KEY_PATH)
    init.add_argument("--public", type=Path, default=PUBLIC_KEY_PATH)
    send = sub.add_parser("seal")
    send.add_argument("--article", type=Path, required=True)
    send.add_argument("--public", type=Path, default=PUBLIC_KEY_PATH)
    args = parser.parse_args()
    if args.command == "keygen":
        make_keypair(args.private, args.public)
        print("KEYPAIR_CREATED; private key remains in local ignored folder")
    else:
        article = json.loads(args.article.read_text(encoding="utf-8"))
        envelope = seal_article(article, args.public.read_bytes())
        print(json.dumps({"mode": "encrypted_article", "envelope": envelope}, separators=(",", ":")))


if __name__ == "__main__":
    main()
