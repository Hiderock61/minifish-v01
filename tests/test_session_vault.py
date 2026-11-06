"""G1: session cookies must never appear as plaintext on disk or in errors."""
from pathlib import Path
import os
import stat

from cryptography.fernet import Fernet
import pytest

from minifish.session_vault import EncryptedSessionVault
from minifish.browser import PlaywrightBrowser

STATE = {
    "cookies": [{"name": "session", "value": "DUMMY_TEST_COOKIE_ONLY",
                 "domain": "127.0.0.1", "path": "/",
                 "expires": -1, "httpOnly": True, "secure": False,
                 "sameSite": "Lax"}],
    "origins": [],
}


def make_vault(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    return EncryptedSessionVault(directory / "account.vault", Fernet.generate_key())


def test_vault_roundtrip_is_encrypted_and_private(tmp_path):
    v = make_vault(tmp_path)
    assert v.load() is None
    v.save(STATE)
    disk = v.path.read_bytes()
    assert b"DUMMY_TEST_COOKIE_ONLY" not in disk
    assert b"session" not in disk
    assert stat.S_IMODE(v.path.stat().st_mode) == 0o600
    assert v.load() == STATE


def test_wrong_key_and_corrupted_file_fail_closed(tmp_path):
    v = make_vault(tmp_path)
    v.save(STATE)
    wrong = EncryptedSessionVault(v.path, Fernet.generate_key())
    with pytest.raises(ValueError, match="SESSION_VAULT_DECRYPT_FAILED"):
        wrong.load()
    v.path.write_bytes(b"tampered or invalid session")
    with pytest.raises(ValueError, match="SESSION_VAULT_DECRYPT_FAILED"):
        v.load()


def test_disallow_world_readable_file(tmp_path):
    v = make_vault(tmp_path)
    v.save(STATE)
    os.chmod(v.path, 0o644)
    with pytest.raises(ValueError, match="SESSION_VAULT_PERMISSIONS_UNSAFE"):
        v.load()
    with pytest.raises(ValueError, match="SESSION_VAULT_PERMISSIONS_UNSAFE"):
        v.save(STATE)


def test_disallow_unsafe_directory_and_symlink(tmp_path):
    root = tmp_path / "weak"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o755)
    v = EncryptedSessionVault(root / "profile.vault", Fernet.generate_key())
    with pytest.raises(ValueError, match="SESSION_VAULT_DIRECTORY_UNSAFE"):
        v.save(STATE)
    target = tmp_path / "original"
    target.write_text("NEVER TOUCH")
    link = tmp_path / "alias.vault"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="SESSION_VAULT_SYMLINK_BLOCKED"):
        EncryptedSessionVault(link, Fernet.generate_key())
    assert target.read_text() == "NEVER TOUCH"


def test_reject_invalid_shape_and_oversized_data(tmp_path):
    v = make_vault(tmp_path)
    with pytest.raises(ValueError, match="SESSION_STATE_INVALID"):
        v.save({"cookies": []})
    with pytest.raises(ValueError, match="SESSION_STATE_TOO_LARGE"):
        v.save({"cookies": [], "origins": [], "padding": "x" * 2_000_000})
    assert not v.path.exists()


def test_legacy_plain_profile_cannot_mix_with_vault(tmp_path):
    with pytest.raises(ValueError, match="SESSION_VAULT_AND_PLAINTEXT_PROFILE_CONFLICT"):
        PlaywrightBrowser(
            profile_path=str(tmp_path / "profile.json"),
            session_vault=make_vault(tmp_path),
        )
