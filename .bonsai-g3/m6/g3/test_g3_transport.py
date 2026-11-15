"""Offline-only test double. An API key is never needed; no network is used."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import os
import pytest
from bonsai_g3_ab import START_PROMPT, T0, SOURCES, B_ADDENDUM
from bonsai_g3_transport import (
    SourceBundle, SourceHold, ExecutionHold, TransportSettings,
    read_pinned_sources, git_blob_sha, run_session, run_pair,
)

class FakeClient:
    def __init__(self, fail_on=None, ready_override=None, incomplete_on=None,
                 missing_markers_on=None):
        self.calls = []
        self.fail_on = fail_on
        self.ready_override = ready_override
        self.incomplete_on = incomplete_on
        self.missing_markers_on = missing_markers_on
        self.responses = self

    def create(self, **kw):
        self.calls.append(kw)
        count = len(self.calls)
        if self.fail_on == count:
            raise RuntimeError('PRIVATE_SUPER_SECRET_DO_NOT_ECHO')
        if self.incomplete_on == count:
            return SimpleNamespace(output_text='truncated', status='incomplete', usage=None)
        if count == 1:
            t = self.ready_override or '🎭 BONSaY 現行候補 v0.1d｜READY'
        elif self.missing_markers_on == count:
            t = '文字だけ。次の更新トリガーはありません。'
        else:
            gen = count - 1
            t = (f'【模擬公演・意味未検査】🌳C-IDEA{gen}\n'
                 '🎭甲｜反応元：同じT｜🆕軸X\n🎭乙｜反応元：同じT｜🆕軸Y\n'
                 '🌳枝生存判定 🌿X ⚔️Y\n🌳次の更新トリガー\n「条件はどう変わる？」')
        return SimpleNamespace(output_text=t, status='completed',
                               usage=SimpleNamespace(input_tokens=120, output_tokens=80))

@pytest.fixture
def source_dir(tmp_path):
    root = tmp_path / 'trusted_source'
    manifest = {}
    for i, rel in enumerate(SOURCES):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = f'MOCK SPEC {i} {rel}\n'.encode()
        p.write_bytes(data)
        manifest[rel] = git_blob_sha(data)
    return root, manifest

@pytest.fixture
def bundle(source_dir):
    root, manifest = source_dir
    return read_pinned_sources(root, manifest)

@pytest.fixture
def settings():
    return TransportSettings(model='offline-fake-sdk')


def test_pinned_sources_byte_verified(bundle):
    assert bundle.verified and len(bundle.texts) == 6
    assert all(s.startswith('MOCK SPEC') for s in bundle.texts.values())


def test_tampered_blob_causes_source_hold(source_dir):
    root, manifest = source_dir
    p = root / list(SOURCES)[0]
    p.write_text('tampered')
    with pytest.raises(SourceHold, match='git_blob_mismatch'):
        read_pinned_sources(root, manifest)


def test_missing_source_and_path_set_hold(source_dir):
    root, manifest = source_dir
    (root / list(SOURCES)[0]).unlink()
    with pytest.raises(SourceHold): read_pinned_sources(root, manifest)
    with pytest.raises(SourceHold): read_pinned_sources(root, {})


def test_symlink_escape_hold(source_dir, tmp_path):
    root, manifest = source_dir
    p = root / list(SOURCES)[0]
    p.unlink()
    external = tmp_path / 'evil'
    external.write_text('no')
    p.symlink_to(external)
    with pytest.raises(SourceHold): read_pinned_sources(root, manifest)


def test_offline_full_3_gen_and_four_calls(tmp_path, bundle, settings):
    fake = FakeClient()
    result = run_session('A', fake, settings, bundle, tmp_path / 'secret_A')
    assert result.status == 'DELIVERY_COMPLETE_AUDIT_PENDING'
    assert result.completed_generations == 3
    assert len(fake.calls) == 4
    assert all(x['store'] is False and x['max_output_tokens'] == 3000 for x in fake.calls)
    assert result.semantic_status.startswith('UNKNOWN')


def test_history_full_each_call_and_no_remote_shortcut(tmp_path, bundle, settings):
    fake = FakeClient()
    run_session('A', fake, settings, bundle, tmp_path / 'secret')
    seq = fake.calls
    assert [len(c['input']) for c in seq] == [2,4,6,8]
    assert seq[1]['input'][-2]['role'] == 'assistant'
    assert seq[1]['input'][-1]['content'] == T0
    assert seq[2]['input'][-1]['content'] == 'あ'
    assert 'MOCK SPEC' in seq[3]['input'][0]['content']


def test_b_only_changes_start_addendum(tmp_path, bundle, settings):
    clients = []
    def make():
        x = FakeClient(); clients.append(x); return x
    result = run_pair(make, settings, bundle, tmp_path / 'private')
    assert len(clients) == 2
    assert result['A']['completed_generations'] == result['B']['completed_generations'] == 3
    a = clients[0].calls[0]['input']
    b = clients[1].calls[0]['input']
    assert a[0] == b[0]
    assert a[-1]['content'] == START_PROMPT
    assert b[-1]['content'] == START_PROMPT + B_ADDENDUM
    assert clients[0].calls[1]['input'][-1]['content'] == T0
    assert clients[1].calls[1]['input'][-1]['content'] == T0


def test_ready_not_received_no_t0(tmp_path, bundle, settings):
    fake = FakeClient(ready_override='READY maybe')
    r = run_session('A', fake, settings, bundle, tmp_path / 'private')
    assert r.status == 'HOLD' and r.calls == 1 and r.completed_generations == 0
    assert r.reason == 'READY_UNVERIFIED'


def test_incomplete_stops_no_retry(tmp_path, bundle, settings):
    fake = FakeClient(incomplete_on=3)
    r = run_session('B', fake, settings, bundle, tmp_path / 'private')
    assert r.calls == 3 and r.completed_generations == 1
    assert r.reason == 'EMPTY_OR_INCOMPLETE_RESPONSE'


def test_api_exception_never_leaks(tmp_path, bundle, settings):
    fake = FakeClient(fail_on=2)
    r = run_session('A', fake, settings, bundle, tmp_path / 'private')
    assert r.calls == 2 and r.status == 'HOLD'
    assert 'SUPER_SECRET' not in json.dumps(r.public_summary())
    assert 'SUPER_SECRET' not in (tmp_path/'private'/'A_PUBLIC_SAFE_summary.json').read_text()


def test_structure_marker_absence_holds(tmp_path, bundle, settings):
    fake = FakeClient(missing_markers_on=2)
    r = run_session('A', fake, settings, bundle, tmp_path / 'private')
    assert r.status == 'HOLD' and r.completed_generations == 0 and r.calls == 2


def test_no_implicit_live_key_use(tmp_path, bundle, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'DO_NOT_USE')
    fake = FakeClient()
    settings = TransportSettings(model='fake')
    run_session('A', fake, settings, bundle, tmp_path / 'private')
    assert 'DO_NOT_USE' not in (tmp_path/'private'/'A_PUBLIC_SAFE_summary.json').read_text()


def test_live_requires_separate_explicit_gate(tmp_path, bundle, monkeypatch):
    fake = FakeClient()
    setting = TransportSettings(model='mock', mode='live', allow_billable=False)
    monkeypatch.setenv('MINIFISH_G3_REAL_API_CONSENT', 'yes')
    with pytest.raises(ExecutionHold): run_session('A', fake, setting, bundle, tmp_path/'p')
    monkeypatch.delenv('MINIFISH_G3_REAL_API_CONSENT')
    with pytest.raises(ExecutionHold): run_session('A', fake, replace(setting, allow_billable=True), bundle, tmp_path/'p')
    assert not fake.calls


def test_private_transcript_and_public_summary_separate(tmp_path, bundle, settings):
    p = tmp_path / 'secret'; fake = FakeClient()
    r = run_session('B', fake, settings, bundle, p)
    assert r.status == 'DELIVERY_COMPLETE_AUDIT_PENDING'
    transcript = json.loads((p/'B_PRIVATE_transcript.json').read_text())
    public = json.loads((p/'B_PUBLIC_SAFE_summary.json').read_text())
    assert len(transcript['history']) == 8
    assert 'history' not in public
    assert 'MOCK SPEC' not in json.dumps(public)
    assert (p.stat().st_mode & 0o077) == 0
    assert ((p/'B_PRIVATE_transcript.json').stat().st_mode & 0o077) == 0


def test_no_duplicate_evidence_overwrite(tmp_path, bundle, settings):
    path = tmp_path/'private'
    run_session('A', FakeClient(), settings, bundle, path)
    with pytest.raises(FileExistsError): run_session('A', FakeClient(), settings, bundle, path)


def test_invalid_source_bundle_fails_before_model_call(tmp_path, bundle, settings):
    fake = FakeClient()
    bad = SourceBundle(texts={}, manifest={}, verified=False)
    with pytest.raises(SourceHold): run_session('A', fake, settings, bad, tmp_path/'p')
    assert not fake.calls


def test_unsupported_condition_never_calls(tmp_path, bundle, settings):
    fake = FakeClient()
    with pytest.raises(ExecutionHold): run_session('C', fake, settings, bundle, tmp_path/'p')
    assert not fake.calls


def test_live_uses_only_official_pinned_sources_before_any_call(tmp_path, bundle, monkeypatch):
    fake = FakeClient()
    monkeypatch.setenv('MINIFISH_G3_REAL_API_CONSENT', 'yes')
    setting = TransportSettings(model='approved-model', mode='live', allow_billable=True)
    with pytest.raises(SourceHold, match='official_pinned'):
        run_session('A', fake, setting, bundle, tmp_path/'p')
    assert not fake.calls


def test_same_client_reuse_refused_before_any_call(tmp_path, bundle, settings):
    shared = FakeClient()
    with pytest.raises(ExecutionHold, match='independent_session_clients_required'):
        run_pair(lambda: shared, settings, bundle, tmp_path/'private')
    assert shared.calls == []
