"""One-form write worker: prepare first, human approval, save at most once.

This has no network, login, or background execution of its own.
The caller must provide an explicitly approved site and browser session.
Never use it to bypass authentication, CAPTCHA, or anti-bot controls.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .browser import PlaywrightBrowser
from .guard import SupervisorGate
from .models import Action


class DraftBlocked(Exception):
    """Fixed machine-readable codes: no form values or private URLs in errors."""


@dataclass
class PreparedDraft:
    page_url: str
    field_label: str
    text: str
    fingerprint: str
    attempted: bool = False


def _one_by_role(browser: PlaywrightBrowser, role: str, name: str):
    if browser.page is None:
        raise DraftBlocked("BROWSER_NOT_READY")
    locator = browser.page.get_by_role(role, name=name, exact=True)
    if locator.count() != 1:
        raise DraftBlocked("TARGET_NOT_UNIQUE")
    return locator


def prepare_draft(
    browser: PlaywrightBrowser, *, expected_page_url: str,
    field_label: str, text: str,
) -> PreparedDraft:
    """Fill exactly one textarea/textbox; never click a save button."""
    if not text or len(text) > 5000 or not field_label:
        raise DraftBlocked("DRAFT_INVALID")
    if browser.current_url != expected_page_url:
        raise DraftBlocked("UNEXPECTED_PAGE")
    field = _one_by_role(browser, "textbox", field_label)
    action = Action(type="fill", role="textbox", name=field_label, value=text)
    if SupervisorGate().check(action, browser.observe(), [])[0] != "PASS":
        raise DraftBlocked("SUPERVISOR_BLOCKED")
    browser.execute(action)
    if browser.current_url != expected_page_url or field.input_value() != text:
        raise DraftBlocked("DRAFT_MISMATCH")
    return PreparedDraft(
        page_url=expected_page_url, field_label=field_label, text=text,
        fingerprint=sha256(text.encode("utf-8")).hexdigest(),
    )


def save_approved_draft(
    browser: PlaywrightBrowser, prepared: PreparedDraft, *,
    human_approved: bool,
    save_button: str,
    saved_page_url: str,
    success_heading: str,
) -> dict[str, str]:
    """Fail closed and forbid duplicate submission, even after ambiguous errors.

    Use only after a person has explicitly approved the contents and destination.
    """
    if prepared.attempted:
        raise DraftBlocked("DUPLICATE_SAVE_STOP")
    if not human_approved:
        return {"status": "WAITING_APPROVAL"}
    if browser.current_url != prepared.page_url:
        raise DraftBlocked("PAGE_CHANGED_STOP")
    field = _one_by_role(browser, "textbox", prepared.field_label)
    if field.input_value() != prepared.text:
        raise DraftBlocked("INPUT_CHANGED_STOP")
    _one_by_role(browser, "button", save_button)
    # Claim the one permitted attempt before the first side effect.
    prepared.attempted = True
    try:
        browser.execute(Action(type="click", role="button", name=save_button))
    except Exception:
        raise DraftBlocked("SAVE_OUTCOME_UNKNOWN_STOP") from None
    if browser.current_url != saved_page_url:
        raise DraftBlocked("SAVE_NOT_CONFIRMED_STOP")
    page = browser.page
    assert page is not None
    if page.get_by_role("heading", name=success_heading, exact=True).count() != 1:
        raise DraftBlocked("SAVE_NOT_CONFIRMED_STOP")
    if page.get_by_text(prepared.text, exact=True).count() != 1:
        raise DraftBlocked("SAVED_TEXT_MISMATCH_STOP")
    # Independent second READ (without repeating the POST) is essential.
    browser.goto(saved_page_url)
    if (browser.current_url != saved_page_url
            or page.get_by_text(prepared.text, exact=True).count() != 1):
        raise DraftBlocked("RELOAD_MISMATCH_STOP")
    return {"status": "SAVED_VERIFIED", "sha256": prepared.fingerprint}
