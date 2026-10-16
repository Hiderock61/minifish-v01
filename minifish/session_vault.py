"""Private encrypted storage for a single owner's Playwright session.

Intentionally separate from public GitHub Issues, Actions artifacts and
the legacy plaintext profile.json. A key must be supplied from a private
runtime; no automatic key upload or logging. No real-site login here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

MAX_STATE_BYTES = 2_000_000
# Fernet ciphertext is base64 encoded and larger than its plaintext.
MAX_VAULT_BYTES = 3_000_000


class EncryptedSessionVault:
    def __init__(self, path: str | Path, key: bytes):
        self.path = Path(path)
        self._cipher = Fernet(key)
        if self.path.is_symlink():
            raise ValueError("SESSION_VAULT_SYMLINK_BLOCKED")

    @staticmethod
    def _validate(state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ValueError("SESSION_STATE_INVALID")
        if not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise ValueError("SESSION_STATE_INVALID")
        return state

    def load(self) -> dict[str, Any] | None:
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        except OSError:
            raise ValueError("SESSION_VAULT_OPEN_BLOCKED") from None
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) & 0o077:
                raise ValueError("SESSION_VAULT_PERMISSIONS_UNSAFE")
            if meta.st_size <= 0 or meta.st_size > MAX_VAULT_BYTES:
                raise ValueError("SESSION_VAULT_SIZE_INVALID")
            with os.fdopen(fd, "rb") as reader:
                fd = -1
                ciphertext = reader.read(MAX_VAULT_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
        try:
            cleartext = self._cipher.decrypt(ciphertext)
            if len(cleartext) > MAX_STATE_BYTES:
                raise ValueError("SESSION_VAULT_SIZE_INVALID")
            return self._validate(json.loads(cleartext))
        except (InvalidToken, ValueError, UnicodeError, TypeError):
            raise ValueError("SESSION_VAULT_DECRYPT_FAILED") from None

    def save(self, state: dict[str, Any]) -> None:
        raw = json.dumps(self._validate(state), ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("SESSION_STATE_TOO_LARGE")
        if self.path.is_symlink():
            raise ValueError("SESSION_VAULT_SYMLINK_BLOCKED")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A group-writable directory could let another actor swap vault files.
        mode = stat.S_IMODE(self.path.parent.stat().st_mode)
        if mode & 0o077:
            raise ValueError("SESSION_VAULT_DIRECTORY_UNSAFE")
        existing = self.path.exists()
        if existing:
            current = self.path.lstat()
            if not stat.S_ISREG(current.st_mode) or stat.S_IMODE(current.st_mode) & 0o077:
                raise ValueError("SESSION_VAULT_PERMISSIONS_UNSAFE")
        ciphertext = self._cipher.encrypt(raw)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".session-tmp-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(ciphertext)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
