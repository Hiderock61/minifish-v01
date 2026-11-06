"""MiniFish file-request upload contract, synthetic localhost only."""
import os

import pytest

from minifish import dropbox_upload_mock as mod
from minifish.dropbox_upload_mock import FILE_BODY, FILE_NAME, run_synthetic_upload

RUN_BROWSER = os.getenv("MINIFISH_G1_PRIVATE_MOCK_E2E") == "1"


def test_probe_file_is_fixed_and_contains_no_user_content():
    assert FILE_NAME == "minifish_mock_probe_20261107.txt"
    assert FILE_BODY == b"MINIFISH_SYNTHETIC_UPLOAD_TEST_ONLY\nRESULT=MOCK_ONLY\n"
    assert len(FILE_BODY) < 512


def test_upload_route_blocks_external_network():
    class Req:
        def __init__(self, url, method):
            self.url = url
            self.method = method

    class Route:
        def __init__(self, url, method):
            self.request = Req(url, method)
            self.allowed = None

        def continue_(self):
            self.allowed = True

        def abort(self):
            self.allowed = False

    cases = (
        ("http://127.0.0.1:42000/request", "GET", True),
        ("http://127.0.0.1:42000/upload", "POST", True),
        ("http://127.0.0.1:42000/upload", "GET", False),
        ("http://127.0.0.1:42000/request", "POST", False),
        ("https://127.0.0.1:42000/request", "GET", False),
        ("http://localhost:42000/request", "GET", False),
        ("http://127.0.0.1:42001/request", "GET", False),
        ("http://127.0.0.1:42000/other", "GET", False),
        ("http://127.0.0.1:42000/request?secret=1", "GET", False),
        ("https://www.dropbox.com/request/untrusted", "GET", False),
        ("file:///home/user/.config/secret", "GET", False),
    )
    for url, method, permitted in cases:
        route = Route(url, method)
        mod._local_request_only(route, port=42000)
        assert route.allowed is permitted


@pytest.mark.skipif(not RUN_BROWSER, reason="requires isolated Chromium CI")
def test_real_chromium_uploads_generated_file_to_local_fake_form():
    proof = run_synthetic_upload()
    assert proof.status == "PASS"
    assert proof.submitted == 1
    assert proof.submitted_bytes == len(FILE_BODY)
    assert proof.real_site_calls == proof.paid_api_calls == 0
    assert proof.public_receipt() == {
        "mode": "dropbox_file_request_upload_mock",
        "status": "PASS",
        "mock_upload_count": 1,
        "mock_upload_bytes": len(FILE_BODY),
        "real_site_calls": 0,
        "paid_api_calls": 0,
        "credential_access": 0,
        "real_account_file_uploads": 0,
    }


@pytest.mark.skipif(not RUN_BROWSER, reason="requires isolated Chromium CI")
def test_no_file_is_rejected_without_upload():
    proof = run_synthetic_upload(choose_file=False)
    assert proof.status == "BLOCKED"
    assert proof.submitted == 0
    assert proof.submitted_bytes == 0


def test_public_receipt_excludes_test_file_data_or_upload_endpoint():
    proof = mod.UploadMockProof("PASS", 1, len(FILE_BODY))
    receipt = str(proof.public_receipt())
    for forbidden in ("MINIFISH_SYNTHETIC", "RESULT=MOCK_ONLY",
                      "dropbox.com/request/", "Cookie", "private key"):
        assert forbidden not in receipt
