"""No-cost, offline checks for the fixed three-site MiniFish commander."""
from minifish import readonly_batch


def valid_result(site, **overrides):
    data = {
        "status": "PASS",
        "supervisor_pass": True,
        "api_calls": 0, "paid_calls": 0, "external_writes": 0,
        "credential_access": 0, "browser_actions_executed": 0,
        "observed_url": site.url,
        "run_id": "run_test",
        "title": "public page title",
    }
    data.update(overrides)
    return data


def test_exactly_three_approved_urls_run_once_without_auth(monkeypatch, tmp_path):
    observed = []
    def fake_probe(**kw):
        observed.append(kw)
        site = next(s for s in readonly_batch.PUBLIC_SITES.values()
                    if s.url == kw["url"])
        return valid_result(site)
    monkeypatch.setattr(readonly_batch, "run_public_readonly", fake_probe)
    report = readonly_batch.run_registered_batch(
        issue_number=112, output_root=tmp_path,
    )
    assert report["status"] == "PASS"
    assert [x["site"] for x in report["sites"]] == list(readonly_batch.BATCH_KEYS)
    assert len(observed) == 3
    assert [x["url"] for x in observed] == [
        readonly_batch.PUBLIC_SITES[k].url for k in readonly_batch.BATCH_KEYS
    ]
    assert all("batch_112_" in x["job_id"] for x in observed)
    assert len({str(x["run_dir"]) for x in observed}) == 3
    assert report["api_calls"] == report["paid_calls"] == report["external_writes"] == 0


def test_single_site_failure_fails_whole_batch(monkeypatch, tmp_path):
    def fake_probe(**kw):
        site = next(s for s in readonly_batch.PUBLIC_SITES.values()
                    if s.url == kw["url"])
        return valid_result(site, status="FAIL") if site.key == "python" else valid_result(site)
    monkeypatch.setattr(readonly_batch, "run_public_readonly", fake_probe)
    report = readonly_batch.run_registered_batch(issue_number=113, output_root=tmp_path)
    assert report["status"] == "FAIL"
    assert [x["status"] for x in report["sites"]] == ["PASS", "FAIL", "PASS"]


def test_disallowed_observed_url_or_write_fails_even_when_probe_claims_pass(
    monkeypatch, tmp_path
):
    def fake_probe(**kw):
        site = next(s for s in readonly_batch.PUBLIC_SITES.values()
                    if s.url == kw["url"])
        if site.key == "python":
            return valid_result(site, observed_url="https://attacker.example/", external_writes=1)
        return valid_result(site)
    monkeypatch.setattr(readonly_batch, "run_public_readonly", fake_probe)
    report = readonly_batch.run_registered_batch(issue_number=114, output_root=tmp_path)
    assert report["status"] == "FAIL"
    assert report["sites"][1]["status"] == "FAIL"


def test_exception_no_traceback_or_raw_page_text_leak(monkeypatch, tmp_path):
    def bad(**kw):
        raise RuntimeError("SECRET-HIDDEN-PRIVATE-SESSION")
    monkeypatch.setattr(readonly_batch, "run_public_readonly", bad)
    report = readonly_batch.run_registered_batch(issue_number=115, output_root=tmp_path)
    assert report["status"] == "FAIL"
    assert "SECRET-HIDDEN-PRIVATE-SESSION" not in str(report)
    assert len(report["sites"]) == 3


def test_invalid_issue_number_never_launches_browser(monkeypatch, tmp_path):
    def bad(**kw):
        raise AssertionError("Should not launch!")
    monkeypatch.setattr(readonly_batch, "run_public_readonly", bad)
    for number in (0, -2, 2_000_000_001, True, "123"):
        try:
            readonly_batch.run_registered_batch(issue_number=number, output_root=tmp_path)
        except ValueError as exc:
            assert str(exc) == "INVALID_ISSUE_NUMBER"
        else:
            raise AssertionError("Invalid Issue accepted")
