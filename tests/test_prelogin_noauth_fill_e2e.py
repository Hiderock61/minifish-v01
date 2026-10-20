"""Prove real MiniFish fills a textbox without login or network calls."""
import os
import pytest
from minifish.browser import PlaywrightBrowser
from minifish.models import Action
from minifish.guard import SupervisorGate

LOCAL = "https://minifish-form.invalid/compose"
FORM = """<html lang="ja"><head><title>MiniFish no-login draft</title></head>
<body><h1>自己紹介の入力練習</h1>
<label for="bio">自己紹介</label>
<textarea id="bio"></textarea>
<button type="button" onclick="document.getElementById('echo').textContent=document.getElementById('bio').value">内容確認</button>
<div id="echo"></div></body></html>"""
SAMPLE = "MiniFishの文字入力テスト。ログインも投稿もしていません。"


@pytest.mark.skipif(os.getenv("MINIFISH_PRELOGIN_E2E") != "1",
                    reason="requires the already-installed Chromium, no remote sites")
def test_real_browser_types_and_reads_back_without_login_or_submit():
    network = []
    with PlaywrightBrowser(headless=True, profile_path=None, capture_dir=None) as browser:
        assert browser.context and browser.page
        def route_request(route):
            network.append((route.request.method, route.request.url))
            if route.request.url == LOCAL and route.request.method == "GET":
                route.fulfill(status=200, body=FORM, content_type="text/html; charset=utf-8")
            else:
                route.abort()
        browser.context.route("**/*", route_request)
        browser.goto(LOCAL)
        before = browser.observe()
        assert "自己紹介" in before.aria_snapshot
        assert browser.page.locator("textarea").input_value() == ""
        action = Action(type="fill", role="textbox", name="自己紹介", value=SAMPLE)
        assert SupervisorGate().check(action, before, [])[0] == "PASS"
        result = browser.execute(action)
        assert result["filled"] is True
        assert browser.page.get_by_role("textbox", name="自己紹介").input_value() == SAMPLE
        # No submit button is present; local preview only.
        browser.execute(Action(type="click", role="button", name="内容確認"))
        assert browser.page.locator("#echo").inner_text() == SAMPLE
        assert not browser.page.locator("button[type=submit]").count()
    assert network
    assert all(u == LOCAL and method == "GET" for method, u in network)
