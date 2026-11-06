"""Owner-only real sender contract, verified against synthetic localhost receiver.

No active private Dropbox File Request URL or user data is stored here.
"""
import json
import os
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from minifish import dropbox_upload_mock as mock
from minifish import dropbox_owner_sender as sender

BROWSER = os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") == "1"


def test_exact_dropbox_request_url_only():
    sender._validate_live_url("https://www.dropbox.com/request/fake_synthetic_123456")
    invalid = (
        "https://evil.example/request/fake_synthetic_123456",
        "http://www.dropbox.com/request/fake_synthetic_123456",
        "https://www.dropbox.com.evil.example/request/fake_synthetic_123456",
        "https://www.dropbox.com/request/fake_synthetic_123456?token=secret",
        "https://www.dropbox.com/request/fake_synthetic_123456#fragment",
        "https://www.dropbox.com:443/request/fake_synthetic_123456",
        "https://user:pass@www.dropbox.com/request/fake_synthetic_123456",
        "https://www.dropbox.com/home",
        "file:///home/codespace/.local/share/minifish",
        "http://127.0.0.1:8002/request/mock",
    )
    for url in invalid:
        with pytest.raises(ValueError, match="DROPBOX_REQUEST_URL_NOT_APPROVED"):
            sender._validate_live_url(url)


def test_cross_origin_and_navigation_policy_deny_by_default():
    cases = (
        ("https://www.dropbox.com/request/fake_synthetic_123456", "GET", True, True),
        ("https://www.dropbox.com/request/fake_synthetic_123456", "POST", True, False),
        ("https://www.dropbox.com/other", "GET", True, False),
        ("https://api.dropboxapi.com/2/other", "POST", False, True),
        ("https://static.dropboxstatic.com/s.js", "GET", False, True),
        ("https://evil-dropbox.com/upload", "POST", False, False),
        ("https://www.dropbox.com.evil.example/upload", "POST", False, False),
        ("http://127.0.0.1:8000/request/x", "GET", False, False),
        ("https://www.dropbox.com:443/request/fake_synthetic_123456", "GET", True, False),
        ("file:///tmp/not-owner-synthetic-file", "GET", False, False),
        ("https://static.dropboxstatic.com/test", "POST", False, True),
        ("https://dl.dropboxusercontent.com/user-data", "GET", False, False),
    )
    for url, method, is_main, expected in cases:
        assert sender._can_route(url, method, main_navigation=is_main) is expected


def test_live_probe_requires_codespace_and_explicit_approval(monkeypatch, tmp_path):
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    monkeypatch.setenv("MINIFISH_OWNER_DROPBOX_PROBE_APPROVED", "1")
    monkeypatch.setenv("MINIFISH_PRIVATE_DROPBOX_REQUEST_URL",
                       "https://www.dropbox.com/request/fake_synthetic_123456")
    with pytest.raises(ValueError, match="OWNER_DROPBOX_PROBE_NOT_AUTHORIZED"):
        sender.run_owner_probe()
    monkeypatch.setenv("CODESPACE_NAME", "fake-test-codespace")
    monkeypatch.delenv("MINIFISH_OWNER_DROPBOX_PROBE_APPROVED", raising=False)
    with pytest.raises(ValueError, match="OWNER_DROPBOX_PROBE_NOT_AUTHORIZED"):
        sender.run_owner_probe()
    # The independent pytest guard means even fake Codespace env is insufficient.
    monkeypatch.setenv("MINIFISH_OWNER_DROPBOX_PROBE_APPROVED", "1")
    with pytest.raises(ValueError, match="OWNER_DROPBOX_PROBE_NOT_AUTHORIZED"):
        sender.run_owner_probe()


def test_local_mock_rejects_codespaces_even_with_test_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    monkeypatch.setenv("CODESPACE_NAME", "fake-codespace")
    with pytest.raises(ValueError, match="LOCAL_UPLOAD_MOCK_DISABLED"):
        sender.run_owner_probe(
            local_test_url="http://127.0.0.1:60000/request",
            marker_dir=tmp_path,
        )


def test_marker_is_single_use_and_never_stores_url(tmp_path):
    marker = tmp_path / "one-time"
    sender._mark_attempt(marker)
    assert (marker / sender._MARKER_NAME).read_bytes() == b"ATTEMPTED\n"
    assert oct((marker / sender._MARKER_NAME).stat().st_mode & 0o777) == "0o600"
    with pytest.raises(ValueError, match="OWNER_PROBE_ALREADY_ATTEMPTED"):
        sender._mark_attempt(marker)


def test_bad_marker_permissions_or_symlink_block(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    folder.chmod(0o755)
    with pytest.raises(ValueError, match="OWNER_PROBE_DIR_PERMISSIONS"):
        sender._mark_attempt(folder)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(folder, target_is_directory=True)
    with pytest.raises(ValueError, match="OWNER_PROBE_DIR_SYMLINK"):
        sender._mark_attempt(symlink)


def test_public_receipt_is_allowlisted_and_contains_no_secret_url():
    r = sender.OwnerUploadReceipt("SUBMISSION_ATTEMPTED_UNVERIFIED", True, False)
    result = json.dumps(r.public_receipt())
    for fragment in ("www.dropbox.com", "request/", "credentials",
                     sender._URL_ENV, sender._PROBE_FILE, "owner_private_inbox"):
        assert fragment not in result
    assert r.public_receipt()["status"] == "SUBMISSION_ATTEMPTED_UNVERIFIED"
    assert r.public_receipt()["real_account_data_uploaded"] is False


@pytest.mark.skipif(not BROWSER, reason="requires Chromium-enabled fake site")
def test_exact_sender_code_uploads_one_generated_file_and_replay_is_blocked(
        tmp_path, monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")
    monkeypatch.setattr(mock, "FILE_NAME", sender._PROBE_FILE)
    monkeypatch.setattr(mock, "FILE_BODY", sender._PROBE_BODY)

    mock._MockUploadReceiver.upload_count = 0
    mock._MockUploadReceiver.upload_bytes = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                  mock._MockUploadReceiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/request"
        result = sender.run_owner_probe(
            local_test_url=url, marker_dir=tmp_path / "one-time",
        )
        assert result.status == "MOCK_UPLOAD_PASS"
        assert result.attempted is True
        assert result.local_test is True
        assert mock._MockUploadReceiver.upload_count == 1
        assert mock._MockUploadReceiver.upload_bytes == len(sender._PROBE_BODY)
        with pytest.raises(ValueError, match="OWNER_PROBE_ALREADY_ATTEMPTED"):
            sender.run_owner_probe(
                local_test_url=url, marker_dir=tmp_path / "one-time",
            )
        assert mock._MockUploadReceiver.upload_count == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.skipif(not BROWSER, reason="requires Chromium-enabled fake site")
def test_sender_is_fail_closed_when_file_input_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    monkeypatch.setenv("MINIFISH_G1_PRIVATE_MOCK_E2E", "1")

    class MissingInput(mock._MockUploadReceiver):
        def do_GET(self):
            self._reply(200, "<html><body>No file selector</body></html>")

    server = ThreadingHTTPServer(("127.0.0.1", 0), MissingInput)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        outcome = sender.run_owner_probe(
            local_test_url=f"http://127.0.0.1:{server.server_port}/request",
            marker_dir=tmp_path / "failed",
        )
        assert outcome.status == "STOP_FILE_INPUT_NOT_UNIQUE"
        assert outcome.attempted is False
        assert (tmp_path / "failed" / sender._MARKER_NAME).is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
