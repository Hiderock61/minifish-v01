"""MiniFish note draft conveyor.

One author-approved article -> structured package -> draft-only browser edit ->
verified saved state. No publishing route, no private API calls, no paid AI.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import json
import os
import re
from typing import Any

from .auth import SiteAuth, check_login, load_site, preflight_action, state_path
from .browser import PlaywrightBrowser
from .models import Action

_ALLOWED_TARGETS = frozenset({"note", "ononoke"})
_SAFE_SLUG = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    series: str = ""
    tags: tuple[str, ...] = ()
    magazine: str = ""
    source: str = "chatgpt"
    destinations: tuple[str, ...] = ("note",)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        title = data.get("title")
        body = data.get("body")
        if not isinstance(title, str) or not title.strip() or len(title) > 240:
            raise ValueError("title must be 1-240 characters")
        if not isinstance(body, str) or not body.strip() or len(body) > 100000:
            raise ValueError("body must be 1-100000 characters")
        tags = data.get("tags", [])
        targets = data.get("destinations", ["note"])
        if (not isinstance(tags, list) or len(tags) > 30 or
                not all(isinstance(t, str) and t.strip() and len(t) <= 80 for t in tags)):
            raise ValueError("tags must be a list of up to 30 short nonempty strings")
        if (not isinstance(targets, list) or not targets or
                not all(isinstance(t, str) and t in _ALLOWED_TARGETS for t in targets)):
            raise ValueError("destinations must contain note and/or ononoke")
        if len(set(targets)) != len(targets):
            raise ValueError("duplicate destination")
        extras = [data.get(k, "") for k in ("series", "magazine", "source")]
        if not all(isinstance(x, str) and len(x) <= 140 for x in extras):
            raise ValueError("invalid series/magazine/source")
        if data.get("visibility", "draft") != "draft":
            raise ValueError("automatic publication is disabled; use visibility=draft")
        return cls(title.strip(), body, extras[0], tuple(t.lstrip("#").strip() for t in tags),
                   extras[1], extras[2] or "chatgpt", tuple(targets))

    @property
    def content_key(self) -> str:
        data = json.dumps(
            {"title": self.title, "body": self.body, "series": self.series},
            ensure_ascii=False, sort_keys=True,
        )
        return sha256(data.encode("utf-8")).hexdigest()[:20]

    def manifest(self) -> dict[str, Any]:
        return {
            "content_key": self.content_key, "title": self.title,
            "series": self.series, "tags": list(self.tags),
            "magazine": self.magazine, "source": self.source,
            "destinations": list(self.destinations), "visibility": "draft",
            "body_chars": len(self.body),
        }


@dataclass(frozen=True)
class DraftSelectors:
    editor_url: str
    title: str
    body: str
    save: str
    saved_proof: str
    save_label: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftSelectors":
        keys = ("editor_url", "title", "body", "save", "saved_proof", "save_label")
        if not all(isinstance(data.get(k), str) and data[k].strip() for k in keys):
            raise ValueError("editor selectors and explicit draft-save label required")
        label = data["save_label"].strip()
        if any(word in label.lower() for word in ("公開", "publish", "投稿")):
            raise ValueError("publish controls cannot be configured as draft-save")
        if not any(word in label.lower() for word in ("下書き", "draft")):
            raise ValueError("save_label must explicitly say draft/下書き")
        return cls(*(data[k].strip() for k in keys))


def require_one_visible(page, selector: str):
    loc = page.locator(selector)
    if loc.count() != 1 or not loc.is_visible(timeout=2000):
        raise RuntimeError("EDITOR_FIELD_UNVERIFIED")
    return loc


def write_draft(browser: PlaywrightBrowser, article: Article, sel: DraftSelectors,
                site: SiteAuth | None = None, prepared_html: str | None = None) -> str:
    """Operate ONLY clearly configured draft controls; verify a saved indicator."""
    if "note" not in article.destinations:
        raise ValueError("note destination not selected")
    if site:
        site.validate_target(sel.editor_url)
        for action in (
            Action(type="goto", url=sel.editor_url),
            Action(type="fill", selector=sel.title, value=article.title),
            Action(type="fill", selector=sel.body, value=article.body),
            Action(type="click", selector=sel.save, name=sel.save_label),
        ):
            reason = preflight_action(site, action)
            if reason:
                raise ValueError(reason)
    if prepared_html is None:
        browser.goto(sel.editor_url)
    elif site:
        raise ValueError("HTML mock cannot be used with live authenticated site")
    page = browser.page
    assert page is not None
    if prepared_html is not None:
        page.set_content(prepared_html)
    if site:
        try:
            site.validate_target(page.url)
        except ValueError as exc:
            raise RuntimeError("AUTH_REQUIRED: editor redirected off site") from exc
        if site.login_detected(page.url):
            raise RuntimeError("AUTH_REQUIRED: editor redirected to sign-in")
    title = require_one_visible(page, sel.title)
    body = require_one_visible(page, sel.body)
    save = require_one_visible(page, sel.save)
    # Reject a changed UI: the actual visible button must still explicitly say draft.
    text = (save.inner_text(timeout=2000) or save.get_attribute("aria-label") or "").strip()
    if sel.save_label not in text or any(w in text.lower() for w in ("公開", "publish", "投稿")):
        raise RuntimeError("DRAFT_SAVE_BUTTON_UNVERIFIED")
    title.fill(article.title)
    body.fill(article.body)
    def content(loc):
        # note's rich editor may use contenteditable instead of a textarea.
        tag = loc.evaluate("(element) => element.tagName.toLowerCase()")
        return loc.input_value() if tag in ("input", "textarea") else loc.inner_text()
    if content(title) != article.title:
        raise RuntimeError("TITLE_NOT_ENTERED")
    if content(body) != article.body:
        raise RuntimeError("BODY_NOT_ENTERED")
    save.click(timeout=7000)
    try:
        page.locator(sel.saved_proof).wait_for(state="visible", timeout=7000)
    except Exception as exc:
        raise RuntimeError("DRAFT_SAVE_UNVERIFIED") from exc
    if site:
        try:
            site.validate_target(page.url)
        except ValueError as exc:
            raise RuntimeError("DRAFT_SAVE_REDIRECT_UNVERIFIED") from exc
    return page.url


MOCK_EDITOR_HTML = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>Mock note draft editor</title>
<input id="note-title" aria-label="記事タイトル">
<textarea id="note-body" aria-label="記事本文"></textarea>
<button id="save-draft" type="button">下書き保存</button>
<p id="saved-indicator" hidden>下書き保存済み</p>
<script>
document.getElementById('save-draft').addEventListener('click', () => {
  const title = document.getElementById('note-title').value;
  const body = document.getElementById('note-body').value;
  if (title && body) {
    document.getElementById('saved-indicator').hidden = false;
  }
});
</script></html>"""


MOCK_SELECTORS = DraftSelectors(
    editor_url="about:blank", title="#note-title", body="#note-body",
    save="#save-draft", saved_proof="#saved-indicator", save_label="下書き保存",
)


def mock_draft(article: Article) -> dict[str, str]:
    # No account, network, or paid AI. Reuse the same driver as the live route.
    with PlaywrightBrowser(headless=True, save_profile_on_close=False) as browser:
        write_draft(browser, article, MOCK_SELECTORS, prepared_html=MOCK_EDITOR_HTML)
    return {"status": "MOCK_DRAFT_VERIFIED", "content_key": article.content_key}


def run_live(article: Article, *, config: Path, selectors_path: Path,
             state_root: Path, site_id: str = "note_jp") -> dict[str, str]:
    """Live is opt-in, draft-only; never claims success without explicit site UI proof."""
    if not _SAFE_SLUG.fullmatch(site_id):
        raise ValueError("invalid site id")
    site = load_site(site_id, config)
    if urlsplit(site.base_url).hostname != "note.com":
        raise ValueError("live note target must be note.com")
    selectors = DraftSelectors.from_dict(json.loads(selectors_path.read_text(encoding="utf-8")))
    state = state_path(site_id, state_root)
    if not state.is_file():
        return {"status": "AUTH_REQUIRED", "content_key": article.content_key}
    with PlaywrightBrowser(headless=True, profile_path=str(state),
                           save_profile_on_close=False) as browser:
        if not check_login(browser, site):
            return {"status": "AUTH_REQUIRED", "content_key": article.content_key}
        url = write_draft(browser, article, selectors, site)
    return {"status": "DRAFT_SAVED", "content_key": article.content_key, "draft_url": url}


def main() -> int:
    ap = argparse.ArgumentParser(description="MiniFish note draft conveyor")
    ap.add_argument("job_file", type=Path, help="local JSON article, never commit private drafts")
    ap.add_argument("--mock", action="store_true", help="test form saving without note login")
    ap.add_argument("--live", action="store_true", help="save draft on real note (requires auth)")
    ap.add_argument("--site-config", type=Path, default=Path(".minifish/auth_sites.json"))
    ap.add_argument("--editor-selectors", type=Path, default=Path(".minifish/note_editor.json"))
    ap.add_argument("--state-root", type=Path, default=Path(".minifish/sites"))
    args = ap.parse_args()
    if args.mock == args.live:
        ap.error("choose exactly one of --mock and --live")
    article = Article.from_dict(json.loads(args.job_file.read_text(encoding="utf-8")))
    try:
        out = mock_draft(article) if args.mock else run_live(
            article, config=args.site_config, selectors_path=args.editor_selectors,
            state_root=args.state_root)
    except Exception as exc:
        # No user content, URL queries, cookies, or form values in error output.
        out = {"status": "FAILED", "failure_type": type(exc).__name__,
               "content_key": article.content_key}
    print(json.dumps({**article.manifest(), **out}, ensure_ascii=False, indent=2))
    return 0 if out["status"] in ("MOCK_DRAFT_VERIFIED", "DRAFT_SAVED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
