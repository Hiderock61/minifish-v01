"""G1-prelogin: four approved login entrances. Never authenticate or submit.

This is a ONE-SHOT, no-session, read-only inspection, not a login robot.
No cookies, passwords, profile contents, snapshots or credentials are exported.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from typing import Any

from .browser import PlaywrightBrowser


@dataclass(frozen=True)
class LoginSite:
    key: str
    label: str
    login_url: str
    host: str


SITES = {
    "lancers": LoginSite("lancers", "ランサーズ", "https://www.lancers.jp/user/login", "www.lancers.jp"),
    "coconala": LoginSite("coconala", "ココナラ", "https://coconala.com/login", "coconala.com"),
    "crowdworks": LoginSite("crowdworks", "クラウドワークス", "https://crowdworks.jp/login", "crowdworks.jp"),
    "note": LoginSite("note", "note", "https://note.com/login", "note.com"),
}


def safe_login_site(key: str) -> LoginSite:
    if not isinstance(key, str) or key not in SITES:
        raise ValueError("G1_PRELOGIN_SITE_NOT_APPROVED")
    site = SITES[key]
    url = urlsplit(site.login_url)
    if (url.scheme != "https" or url.hostname != site.host
            or url.username or url.password or url.query or url.fragment
            or url.port is not None):
        raise ValueError("G1_PRELOGIN_URL_INVALID")
    return site


def observe_login_only(key: str, *, timeout_ms: int = 15000) -> dict[str, Any]:
    """One fixed public GET; no login fields are filled or submitted."""
    site = safe_login_site(key)
    report = {
        "site": site.key,
        "label": site.label,
        "status": "BLOCKED",
        "stop": "HUMAN_LOGIN_REQUIRED",
        "auth_attempts": 0,
        "form_fills": 0,
        "form_submits": 0,
        "external_writes": 0,
        "openai_api_calls": 0,
    }
    try:
        # No storage-state path and no logged in profile. Independent browser.
        with PlaywrightBrowser(headless=True, profile_path=None, capture_dir=None) as browser:
            context, page = browser.context, browser.page
            assert context is not None and page is not None
            # No network mutations. Disallow top-level navigation to other sites.
            def route_request(route):
                req = route.request
                parsed = urlsplit(req.url)
                if req.method not in ("GET", "HEAD"):
                    route.abort()
                elif (req.is_navigation_request() and req.frame == page.main_frame
                      and (parsed.scheme != "https" or parsed.hostname != site.host)):
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", route_request)
            response = page.goto(site.login_url, wait_until="domcontentloaded", timeout=timeout_ms)
            p = urlsplit(page.url)
            if (p.scheme != "https" or p.hostname != site.host or
                    (response is not None and response.status >= 400)):
                report["status"] = "BLOCKED"
                report["reason"] = "G1_LOGIN_SITE_REJECTED_OR_REDIRECTED"
                return report
            page.wait_for_timeout(500)
            # Text-only evidence of login inputs, not their values.
            num_password = page.locator('input[type="password"]').count()
            num_user = page.locator('input[type="email"], input[name*="mail"], input[name*="login"], input[type="text"]').count()
            report["status"] = (
                "LOGIN_FIELDS_VISIBLE" if num_password and num_user
                else "LOGIN_PAGE_ONLY"
            )
            report["reason"] = (
                "G1_STOP_BEFORE_CREDENTIALS" if num_password and num_user
                else "G1_LOGIN_FIELDS_NOT_CONFIRMED"
            )
            # Stop. Never pass back HTML, screenshot, cookies, inputs or browser profile.
            return report
    except Exception:
        report["reason"] = "G1_READ_ONLY_BROWSER_UNAVAILABLE"
        return report


def summary() -> dict[str, Any]:
    """A predictable checklist without visiting the sites."""
    return {
        "purpose": "FOUR_LOGIN_HANDOFFS_NO_AUTH",
        "site_count": len(SITES),
        "login_pending": True,
        "login_credentials_requested": False,
        "site_keys": tuple(SITES),
        "openai_api_calls": 0,
        "external_writes": 0,
        "next_human_action": "LOGIN_WHEN_USER_CHOOSES",
    }
