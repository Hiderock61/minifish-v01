"""Local-only proof that MiniFish's Playwright can submit a GENERATED text file.

The receiver is a synthetic HTTP form bound to 127.0.0.1. This code has
no real Dropbox request URL, no owner login/Vault, no credentials, no
external web requests, no paid API, and no automatic Codespace activation.
"""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from .browser import PlaywrightBrowser

FILE_NAME = "minifish_mock_probe_20261107.txt"
FILE_BODY = b"MINIFISH_SYNTHETIC_UPLOAD_TEST_ONLY\nRESULT=MOCK_ONLY\n"
_MAX_REQUEST_BYTES = 4096
_FORM = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<h1>FAKE_FILE_REQUEST_ONLY</h1>
<form action="/upload" enctype="multipart/form-data" method="post">
<label for="upload">Synthetic document</label>
<input type="file" id="upload" name="file" accept=".txt">
<button type="submit">Send synthetic file</button>
</form></body></html>"""


class _MockUploadReceiver(BaseHTTPRequestHandler):
    upload_count = 0
    upload_bytes = 0
    expected_size = len(FILE_BODY)

    def log_message(self, *args):
        pass  # no raw URL, file content, headers or request body are logged

    def _reply(self, code: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path != "/request":
            return self._reply(404, "NOT_FOUND")
        self._reply(200, _FORM)

    def do_POST(self) -> None:
        if self.path != "/upload":
            return self._reply(404, "NOT_FOUND")
        ctype = self.headers.get("Content-Type", "")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._reply(400, "BAD_LENGTH")
        if (not ctype.startswith("multipart/form-data; boundary=")
                or length <= 0 or length > _MAX_REQUEST_BYTES):
            return self._reply(400, "INVALID_MULTIPART")
        raw = self.rfile.read(length)
        mime = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + ctype + "\r\n"
             "MIME-Version: 1.0\r\n\r\n").encode("utf-8") + raw
        )
        matches = [
            item for item in mime.iter_parts()
            if item.get_content_disposition() == "form-data"
            and item.get_param("name", header="content-disposition") == "file"
        ] if mime.is_multipart() else []
        if (len(matches) != 1 or matches[0].get_filename() != FILE_NAME
                or matches[0].get_payload(decode=True) != FILE_BODY):
            return self._reply(422, "<p id='result'>REJECTED</p>")
        type(self).upload_count += 1
        type(self).upload_bytes = len(FILE_BODY)
        self._reply(200, "<p id='result'>SYNTHETIC_UPLOAD_OK</p>")


def _local_request_only(route, *, port: int) -> None:
    req = route.request
    target = urlsplit(req.url)
    permitted = (
        target.scheme == "http" and target.hostname == "127.0.0.1"
        and target.port == port and target.username is None
        and target.password is None and not target.query
        and not target.fragment
        and ((req.method == "GET" and target.path == "/request")
             or (req.method == "POST" and target.path == "/upload"))
    )
    if permitted:
        route.continue_()
    else:
        route.abort()


@dataclass(frozen=True)
class UploadMockProof:
    status: str
    submitted: int
    submitted_bytes: int
    local_only: bool = True
    real_site_calls: int = 0
    paid_api_calls: int = 0

    def public_receipt(self) -> dict[str, object]:
        return {
            "mode": "dropbox_file_request_upload_mock",
            "status": self.status,
            "mock_upload_count": self.submitted,
            "mock_upload_bytes": self.submitted_bytes,
            "real_site_calls": self.real_site_calls,
            "paid_api_calls": self.paid_api_calls,
            "credential_access": 0,
            "real_account_file_uploads": 0,
        }


def run_synthetic_upload(*, choose_file: bool = True) -> UploadMockProof:
    """One browser-form upload, or no-file failure, to a LOCAL fake receiver.

    No implicit GitHub Issues or Codespaces invocation. The generated text
    file exists only in a disposable local directory and is never sourced
    from the user's filesystem or decrypted owner Vault.
    """
    with TemporaryDirectory(prefix="minifish-file-request-mock-") as folder:
        root = Path(folder)
        probe = root / FILE_NAME
        probe.write_bytes(FILE_BODY)
        probe.chmod(0o600)
        _MockUploadReceiver.upload_count = 0
        _MockUploadReceiver.upload_bytes = 0

        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockUploadReceiver)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        try:
            with PlaywrightBrowser(headless=True, profile_path=None,
                                   session_vault=None, capture_dir=None,
                                   save_session_on_exit=False) as browser:
                assert browser.page is not None and browser.context is not None
                browser.context.route("**/*", lambda r:
                                      _local_request_only(r, port=port))
                browser.goto(f"http://127.0.0.1:{port}/request")
                if choose_file:
                    browser.page.locator('input[type="file"]').set_input_files(
                        str(probe)
                    )
                browser.page.get_by_role(
                    "button", name="Send synthetic file"
                ).click(timeout=7000)
                browser.page.locator("#result").wait_for(timeout=7000)
                result = browser.page.locator("#result").inner_text(timeout=3000)

            count = _MockUploadReceiver.upload_count
            sent = _MockUploadReceiver.upload_bytes
            passed = (
                choose_file and result == "SYNTHETIC_UPLOAD_OK"
                and count == 1 and sent == len(FILE_BODY)
            )
            # A missing file MUST fail without making a successful upload.
            blocked = (
                not choose_file and count == 0 and result == "REJECTED"
            )
            return UploadMockProof(
                status="PASS" if passed else "BLOCKED" if blocked else "FAIL",
                submitted=count, submitted_bytes=sent,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
