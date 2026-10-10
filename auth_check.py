"""Check saved login state in fresh headless Chromium without AI or credentials."""
from __future__ import annotations

import argparse
import os

from minifish.auth import check_login, load_site, state_path
from minifish.browser import PlaywrightBrowser


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("site_id")
    p.add_argument("--config", default=os.getenv("MINIFISH_AUTH_CONFIG", ".minifish/auth_sites.json"))
    p.add_argument("--state-root", default=os.getenv("MINIFISH_AUTH_STATE_ROOT", ".minifish/sites"))
    args = p.parse_args()
    try:
        site = load_site(args.site_id, args.config)
        storage = state_path(site.site_id, args.state_root)
        if not storage.is_file():
            print("AUTH_REQUIRED: no saved profile")
            return 1
        with PlaywrightBrowser(headless=True, profile_path=str(storage),
                               save_profile_on_close=False) as browser:
            ok = check_login(browser, site)
        print("AUTH_OK: saved session restored" if ok else "AUTH_REQUIRED: login expired")
        return 0 if ok else 1
    except (OSError, ValueError) as exc:
        print(f"AUTH_ERROR: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
