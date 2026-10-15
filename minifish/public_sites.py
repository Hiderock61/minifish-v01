"""Explicit catalog of unauthenticated, public URLs for zero-cost missions.

All entries are exact HTTPS URLs. No user-supplied path, query or port can
ever be used as a destination. Adding a site requires code review and tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PublicSite:
    key: str
    url: str
    host: str
    path_prefix: str
    title_contains: str


PUBLIC_SITES: dict[str, PublicSite] = {
    "example": PublicSite(
        "example", "https://example.com/", "example.com", "/", "Example Domain"
    ),
    "python": PublicSite(
        "python", "https://docs.python.org/3/", "docs.python.org", "/3/", "Python"
    ),
    "github": PublicSite(
        "github", "https://github.com/Hiderock61/minifish-v01",
        "github.com", "/Hiderock61/minifish-v01", "GitHub"
    ),
}


def site_for_url(url: str) -> PublicSite | None:
    if not isinstance(url, str):
        return None
    # Strict equality protects against userinfo, scheme, port, query,
    # fragment, alternate host spelling, protocol-relative URLs and SSRF.
    return next((s for s in PUBLIC_SITES.values() if url == s.url), None)


def observed_url_allowed(site: PublicSite, observed_url: str) -> bool:
    try:
        p = urlsplit(observed_url)
        # The URL can legitimately gain a slash or an index.html redirect.
        return (
            p.scheme == "https"
            and p.hostname == site.host
            and p.port is None
            and p.username is None
            and p.password is None
            and not p.query
            and not p.fragment
            and (p.path == site.path_prefix.rstrip("/")
                 or p.path.startswith(site.path_prefix))
        )
    except ValueError:
        return False
