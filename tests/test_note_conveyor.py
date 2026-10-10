import json
import pytest

from minifish.note_conveyor import (
    Article, DraftSelectors, mock_draft, write_draft, run_live, MOCK_SELECTORS, MOCK_EDITOR_HTML
)
from minifish.browser import PlaywrightBrowser
from minifish.auth import SiteAuth


JOB = {
    "title": "Z軸｜第17話",
    "body": "博士は三回右手を上げた。\n\n続く。",
    "series": "Z軸シリーズ",
    "tags": ["#Z軸", "小説"],
    "source": "chatgpt",
    "destinations": ["note"],
    "visibility": "draft",
}


def test_article_preserves_content_and_deduplicates():
    a = Article.from_dict(JOB)
    assert a.title == JOB["title"]
    assert a.body == JOB["body"]
    assert a.tags == ("Z軸", "小説")
    assert a.content_key == Article.from_dict(JOB).content_key
    assert a.manifest()["visibility"] == "draft"
    assert "body" not in a.manifest()


def test_mixed_destinations_are_allowed_as_future_route():
    a = Article.from_dict({**JOB, "destinations": ["note", "ononoke"]})
    assert a.destinations == ("note", "ononoke")


@pytest.mark.parametrize("overrides", [
    {"visibility": "public"},
    {"visibility": "published"},
    {"destinations": ["unknown"]},
    {"body": ""},
    {"tags": [""]},
])
def test_rejects_unsafe_or_incomplete_job(overrides):
    with pytest.raises(ValueError):
        Article.from_dict({**JOB, **overrides})


def test_save_label_cannot_be_publish_button():
    with pytest.raises(ValueError):
        DraftSelectors.from_dict({
            "editor_url": "https://note.com/new", "title": "#title",
            "body": "#body", "save": "#save",
            "saved_proof": "#saved", "save_label": "公開する",
        })


def test_mock_chromium_article_to_draft():
    result = mock_draft(Article.from_dict(JOB))
    assert result["status"] == "MOCK_DRAFT_VERIFIED"


def test_content_is_verified_not_just_clicked():
    article = Article.from_dict(JOB)
    with PlaywrightBrowser(headless=True, save_profile_on_close=False) as browser:
        assert browser.page is not None
        url = write_draft(
            browser, article, MOCK_SELECTORS, prepared_html=MOCK_EDITOR_HTML
        )
        assert url == "about:blank"
        assert browser.page.locator("#note-title").input_value() == article.title
        assert browser.page.locator("#note-body").input_value() == article.body
        assert browser.page.locator("#saved-indicator").is_visible()


def test_live_preflight_blocks_unapproved_write_action():
    article = Article.from_dict(JOB)
    site = SiteAuth.from_dict({
        "site_id": "note_jp", "base_url": "https://note.com",
        "check_url": "https://note.com/account",
        "success_selector": "#profile",
        "login_path_markers": ["/login"],
    })
    selectors = DraftSelectors(
        "https://note.com/new", "#title", "#body", "#save",
        "#saved", "下書き保存",
    )
    with PlaywrightBrowser(headless=True, save_profile_on_close=False) as browser:
        with pytest.raises(ValueError, match="AUTH_POLICY"):
            write_draft(browser, article, selectors, site)


def test_verified_draft_ledger_prevents_duplicate_repost(tmp_path):
    article = Article.from_dict(JOB)
    site_cfg = tmp_path / "auth_sites.json"
    site_cfg.write_text(json.dumps({"sites": [{
        "site_id": "note_jp",
        "base_url": "https://note.com",
        "check_url": "https://note.com/account",
        "success_selector": "#signed-in",
        "login_path_markers": ["/login"],
        "allow_actions": ["goto", "fill", "click", "back", "wait"],
    }]}), encoding="utf-8")
    selectors = tmp_path / "note_editor.json"
    selectors.write_text(json.dumps({
        "editor_url": "https://note.com/new", "title": "#title",
        "body": "#body", "save": "#draft", "saved_proof": "#saved",
        "save_label": "下書き保存",
    }), encoding="utf-8")
    (tmp_path / "note_draft_ledger.json").write_text(json.dumps({
        article.content_key: {"status": "DRAFT_SAVED", "draft_url": "https://note.com/draft/123"}
    }), encoding="utf-8")
    result = run_live(article, config=site_cfg, selectors_path=selectors,
                      state_root=tmp_path / "sites")
    assert result["status"] == "ALREADY_SAVED"
    assert result["draft_url"] == "https://note.com/draft/123"
