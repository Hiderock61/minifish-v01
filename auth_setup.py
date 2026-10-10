"""One-time manual sign-in in the SAME Chromium runtime as MiniFish.
Run only on a trusted local graphical session, not in headless Codespaces.
Never enter passwords in the terminal, chat, or Git.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from minifish.auth import check_login, load_site, state_path
from minifish.browser import PlaywrightBrowser


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("site_id")
    p.add_argument("--config", default=os.getenv("MINIFISH_AUTH_CONFIG", ".minifish/auth_sites.json"))
    p.add_argument("--state-root", default=os.getenv("MINIFISH_AUTH_STATE_ROOT", ".minifish/sites"))
    args = p.parse_args()

    site = load_site(args.site_id, args.config)
    profile = state_path(site.site_id, args.state_root)
    if os.name != "nt" and not os.getenv("DISPLAY") and not os.getenv("WAYLAND_DISPLAY"):
        print("BLOCKED: This command needs a visible browser desktop. Headless Codespaces cannot accept manual sign-in.")
        return 2
    print(f"Opening registered site {site.site_id}. Sign in ONLY in the Chromium window.")
    with PlaywrightBrowser(headless=False, profile_path=str(profile), save_profile_on_close=False) as browser:
        browser.goto(site.check_url)
        input("After finishing login and MFA in Chromium, press ENTER here to verify: ")
        if not check_login(browser, site):
            print("AUTH_REQUIRED: successful login marker not found. No new state was saved.")
            return 1
        browser.save_profile_on_close = True
        print("AUTH_VERIFIED: closing Chromium and saving state under .minifish (not Git).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
