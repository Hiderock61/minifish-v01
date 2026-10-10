"""Site-scoped authentication policy. No passwords or session files live in Git."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import json
import re

_ID = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")


def public_url(url: str) -> str:
    """Remove query/fragment, which often carry tokens."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def origin(url: str) -> tuple[str, str]:
    p = urlsplit(url)
    if p.username or p.password or p.scheme not in ("https", "http") or not p.hostname:
        raise ValueError("invalid HTTP(S) URL")
    # Plain HTTP is permitted only for a local mock test.
    if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("site origin must use HTTPS")
    return p.scheme, p.netloc.lower()


@dataclass(frozen=True)
class SiteAuth:
    site_id: str
    base_url: str
    check_url: str
    success_selector: str
    login_path_markers: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "SiteAuth":
        sid = data.get("site_id", "")
        if not isinstance(sid, str) or not _ID.fullmatch(sid):
            raise ValueError("invalid site_id")
        base = str(data.get("base_url", ""))
        check = str(data.get("check_url", ""))
        if origin(base) != origin(check):
            raise ValueError("check_url must match site origin")
        selector = str(data.get("success_selector", "")).strip()
        if not selector:
            raise ValueError("success_selector is required")
        markers = data.get("login_path_markers", ["/login", "/signin"])
        if not isinstance(markers, list) or not markers or not all(
            isinstance(m, str) and m.startswith("/") for m in markers
        ):
            raise ValueError("login_path_markers must be URL path prefixes")
        return cls(sid, base, check, selector, tuple(m.lower() for m in markers))

    def validate_target(self, url: str) -> None:
        if origin(url) != origin(self.base_url):
            raise ValueError("target URL is outside the registered site origin")

    def login_detected(self, url: str) -> bool:
        p = urlsplit(url)
        path = p.path.lower()
        return any(path.startswith(marker) for marker in self.login_path_markers)


def load_site(site_id: str, config_path: str | Path) -> SiteAuth:
    if not _ID.fullmatch(site_id):
        raise ValueError("invalid site_id")
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    matches = [SiteAuth.from_dict(d) for d in data.get("sites", []) if d.get("site_id") == site_id]
    if len(matches) != 1:
        raise ValueError("site not found or duplicate site_id")
    return matches[0]


def state_path(site_id: str, root: str | Path = ".minifish/sites") -> Path:
    if not _ID.fullmatch(site_id):
        raise ValueError("invalid site_id")
    return Path(root) / site_id / "storage.json"


def check_login(browser, site: SiteAuth, *, navigate: bool = True) -> bool:
    """Fail closed: a visible, site-specific success element is mandatory."""
    try:
        if navigate:
            browser.goto(site.check_url)
        page = browser.page
        if page is None or origin(page.url) != origin(site.base_url):
            return False
        if site.login_detected(page.url):
            return False
        page.locator(site.success_selector).wait_for(state="visible", timeout=5000)
        return True
    except Exception:
        # No guessed success based on cookie presence or a non-login URL.
        return False
