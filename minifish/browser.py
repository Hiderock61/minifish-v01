from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import time

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Playwright

from .models import Observation, Action


class PlaywrightBrowser:
    """Thin browser hand. No planning happens here."""

    def __init__(
        self,
        headless: bool = True,
        executable_path: str | None = None,
        profile_path: str | None = None,
        capture_dir: str | None = None,
    ) -> None:
        self.headless = headless
        self.executable_path = executable_path or os.getenv("MINIFISH_CHROMIUM_PATH")
        self.profile_path = Path(profile_path) if profile_path else None
        self.capture_dir = Path(capture_dir) if capture_dir else None
        if self.capture_dir:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._pw: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "PlaywrightBrowser":
        self._pw = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": ["--no-sandbox"],
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        self.browser = self._pw.chromium.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {}
        if self.profile_path and self.profile_path.exists():
            context_kwargs["storage_state"] = str(self.profile_path)
        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context and self.profile_path:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.context.storage_state(path=str(self.profile_path))
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    @property
    def current_url(self) -> str:
        assert self.page is not None
        return self.page.url

    def goto(self, url: str) -> dict[str, Any]:
        assert self.page is not None
        response = self.page.goto(url, wait_until="domcontentloaded")
        return {
            "ok": True,
            "http_status": response.status if response else None,
            "url": self.page.url,
        }

    def observe(self) -> Observation:
        assert self.page is not None
        title = self.page.title()
        try:
            aria = self.page.locator("body").aria_snapshot(timeout=3000)
        except Exception as e:
            aria = f"<aria unavailable: {type(e).__name__}>"
        try:
            text = self.page.locator("body").inner_text(timeout=3000)
        except Exception:
            text = ""
        return Observation(
            url=self.page.url,
            title=title,
            aria_snapshot=aria[:8000],
            text_excerpt=text[:4000],
        )

    def screenshot(self, step: int) -> str | None:
        assert self.page is not None
        if not self.capture_dir:
            return None
        path = self.capture_dir / f"step_{step:03d}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return str(path)

    def html_capture(self, step: int) -> str | None:
        assert self.page is not None
        if not self.capture_dir:
            return None
        path = self.capture_dir / f"step_{step:03d}.html"
        path.write_text(self.page.content(), encoding="utf-8")
        return str(path)

    def execute(self, action: Action) -> dict[str, Any]:
        assert self.page is not None
        t = action.type
        if t == "goto":
            if not action.url:
                raise ValueError("goto requires url")
            return self.goto(action.url)

        if t == "click":
            locator = self._target(action)
            locator.first.click(timeout=7000)
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            return {"ok": True, "url": self.page.url}

        if t == "fill":
            locator = self._target(action)
            locator.first.fill(action.value or "", timeout=7000)
            return {"ok": True, "url": self.page.url, "filled": True}

        if t == "press":
            if not action.key:
                raise ValueError("press requires key")
            self.page.keyboard.press(action.key)
            return {"ok": True, "key": action.key, "url": self.page.url}

        if t == "back":
            self.page.go_back(wait_until="domcontentloaded")
            return {"ok": True, "url": self.page.url}

        if t == "wait":
            seconds = float(action.seconds or 1.0)
            time.sleep(max(0, min(seconds, 30)))
            return {"ok": True, "waited": seconds, "url": self.page.url}

        if t in ("done", "fail"):
            return {"ok": t == "done", "url": self.page.url}

        raise ValueError(f"Unsupported action type: {t}")

    def _target(self, action: Action):
        assert self.page is not None
        if action.selector:
            return self.page.locator(action.selector)
        if action.role and action.name:
            return self.page.get_by_role(action.role, name=action.name, exact=True)
        if action.name:
            candidates = [
                self.page.get_by_label(action.name, exact=True),
                self.page.get_by_placeholder(action.name, exact=True),
                self.page.get_by_text(action.name, exact=True),
            ]
            for loc in candidates:
                try:
                    if loc.count() > 0:
                        return loc
                except Exception:
                    pass
        raise ValueError("click/fill requires selector or role+name/name")
