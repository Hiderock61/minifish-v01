"""Real public website: type in a search box without login, submission, or API.

This is the bridge between verified real public READ and fake local WRITE.
The input is innocuous; all outbound paths/query parameters are restricted.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .browser import PlaywrightBrowser
from .public_sites import PUBLIC_SITES, observed_url_allowed

PUBLIC_URL = PUBLIC_SITES["python"].url
SEARCH_URL = "https://docs.python.org/3/search.html"
TEXT = "MiniFish browser input check"
MAX_RESOURCE_COUNT = 250


def real_public_typing() -> dict[str, object]:
    report: dict[str, object] = {
        "status": "BLOCKED",
        "site": "python",
        "observed_public_page": False,
        "typing_verified": False,
        "submitted": False,
        "request_with_query": False,
        "http_mutations_allowed": 0,
        "login_attempts": 0,
        "api_calls": 0,
        "external_writes": 0,
    }
    allowed_paths = {"/3/", "/3/search.html"}
    requests_seen = [0]

    def only_safe_public_get(route) -> None:
        req = route.request
        p = urlsplit(req.url)
        # Resource GETs only, on the exact registered public host and /3/ tree.
        # Block input-bearing queries/URL fragments and all offsite requests.
        safe = (
            req.method in ("GET", "HEAD")
            and p.scheme == "https"
            and p.hostname == "docs.python.org"
            and p.port is None
            and p.username is None and p.password is None
            and not p.query and not p.fragment
            and (p.path.startswith("/3/") or p.path == "/3")
            and requests_seen[0] < MAX_RESOURCE_COUNT
        )
        requests_seen[0] += 1
        if safe:
            route.continue_()
        else:
            route.abort()

    try:
        with PlaywrightBrowser(
            headless=True, profile_path=None, capture_dir=None
        ) as browser:
            if browser.context is None or browser.page is None:
                report["reason"] = "BROWSER_NOT_READY"
                return report
            browser.context.route("**/*", only_safe_public_get)
            response = browser.page.goto(PUBLIC_URL, wait_until="domcontentloaded", timeout=20000)
            if (response is None or response.status != 200 or
                    not observed_url_allowed(PUBLIC_SITES["python"], browser.current_url)):
                report["reason"] = "PUBLIC_READ_FAILED"
                return report
            if "Documentation" not in browser.page.title():
                report["reason"] = "PUBLIC_PAGE_UNEXPECTED"
                return report
            report["observed_public_page"] = True
            # Search is part of the official Python docs and needs no account.
            response = browser.page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=16000)
            if (response is None or response.status != 200 or
                    browser.current_url != SEARCH_URL):
                report["reason"] = "SEARCH_PAGE_UNAVAILABLE"
                return report

            # Different Sphinx versions may use a searchbox or q textbox.
            # Never infer selectors beyond these known non-sensitive input types.
            candidates = (
                "input[name='q']",
                "input[type='search']",
                "input[aria-label='Search']",
                "input[placeholder*='Search']",
                "input[placeholder*='search']",
            )
            target = None
            for selector in candidates:
                items = browser.page.locator(selector)
                for n in range(min(4, items.count())):
                    one = items.nth(n)
                    if one.is_visible() and one.is_enabled():
                        target = one
                        break
                if target is not None:
                    break
            if target is None:
                report["reason"] = "SEARCH_INPUT_NOT_VISIBLE"
                return report

            # This is a real browser fill on a real external website.
            # We deliberately do NOT submit, click a submit button or press Enter.
            target.fill(TEXT, timeout=5000)
            if target.input_value() != TEXT:
                report["reason"] = "INPUT_READBACK_MISMATCH"
                return report
            if browser.current_url != SEARCH_URL:
                report["reason"] = "UNEXPECTED_NAVIGATION"
                return report
            report["typing_verified"] = True
            report["status"] = "PASS"
            report["reason"] = "REAL_PUBLIC_INPUT_NOT_SUBMITTED"
            return report
    except Exception:
        report["reason"] = "PUBLIC_BROWSER_OR_INPUT_ERROR"
        return report


def main() -> None:
    result = real_public_typing()
    # Allowlist only safe metadata. No HTML, content, cookies, secrets, query.
    print("MINIFISH_REAL_PUBLIC_INPUT=" + result["status"])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
