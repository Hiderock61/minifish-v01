"""Unauthenticated localhost writing: fill -> approval -> save -> reload.

Uses an isolated HTTP server running in the GitHub Actions test process.
No real websites, sessions, passwords, API calls or external writes.
"""
from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from minifish.browser import PlaywrightBrowser
from minifish.form_draft import DraftBlocked, prepare_draft, save_approved_draft

DRAFT = "MiniFish実証：ログイン不要の練習ページに文章を1回保存しました。"


@pytest.mark.skipif(os.getenv("MINIFISH_LOCAL_SAVE_E2E") != "1",
                    reason="needs installed Chromium, localhost-only fake form")
def test_no_login_form_persisted_after_reload_with_exactly_one_post():
    storage = {"value": "", "writes": 0}
    recorded = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, body, *, redirect=None):
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            if redirect is not None:
                self.send_header("Location", redirect)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/edit":
                self.respond(200,
                    '<html lang="ja"><title>MiniFish 記入練習</title><body>'
                    '<h1>架空プロフィール編集</h1>'
                    '<form method="post" action="/save">'
                    '<label for="bio">自己紹介</label>'
                    '<textarea id="bio" name="bio"></textarea>'
                    '<button type="submit">保存</button></form></body></html>')
            elif self.path == "/saved":
                self.respond(200,
                    '<html lang="ja"><title>保存結果</title><body>'
                    '<h1>保存しました</h1>'
                    '<p id="stored">' + escape(storage["value"]) +
                    '</p></body></html>')
            else:
                self.respond(404, "<h1>ERROR</h1>")

        def do_POST(self):
            if self.path != "/save":
                return self.respond(404, "<h1>ERROR</h1>")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 5000:
                return self.respond(400, "invalid")
            raw = self.rfile.read(size).decode("utf-8")
            storage["value"] = parse_qs(raw).get("bio", [""])[0]
            storage["writes"] += 1
            self.respond(303, "", redirect="/saved")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    edit = root + "/edit"
    saved = root + "/saved"
    try:
        with PlaywrightBrowser(headless=True, profile_path=None, capture_dir=None) as browser:
            assert browser.context is not None
            def strict_route(route):
                req = route.request
                parsed = urlsplit(req.url)
                allowed = (
                    parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                    and parsed.port == server.server_port
                    and (parsed.path, req.method) in {
                        ("/edit", "GET"), ("/save", "POST"), ("/saved", "GET")
                    }
                )
                recorded.append((req.method, req.url, allowed))
                if allowed:
                    route.continue_()
                else:
                    route.abort()

            browser.context.route("**/*", strict_route)
            browser.goto(edit)
            prepared = prepare_draft(
                browser, expected_page_url=edit, field_label="自己紹介", text=DRAFT
            )
            assert browser.page.get_by_role("textbox", name="自己紹介").input_value() == DRAFT
            assert storage["writes"] == 0
            assert save_approved_draft(
                browser, prepared, human_approved=False,
                save_button="保存", saved_page_url=saved, success_heading="保存しました"
            )["status"] == "WAITING_APPROVAL"
            assert storage["writes"] == 0
            result = save_approved_draft(
                browser, prepared, human_approved=True,
                save_button="保存", saved_page_url=saved, success_heading="保存しました"
            )
            assert result["status"] == "SAVED_VERIFIED"
            assert storage == {"value": DRAFT, "writes": 1}
            with pytest.raises(DraftBlocked, match="DUPLICATE_SAVE_STOP"):
                save_approved_draft(
                    browser, prepared, human_approved=True,
                    save_button="保存", saved_page_url=saved,
                    success_heading="保存しました"
                )
            assert storage["writes"] == 1
            assert recorded and all(x[2] for x in recorded)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_unauthorized_or_mismatched_form_never_starts():
    from minifish.form_draft import PreparedDraft
    item = PreparedDraft("http://127.0.0.1:1234/edit", "自己紹介", "draft", "sha")
    assert item.attempted is False
    assert not hasattr(item, "password")
