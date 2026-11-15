"""M5: contract tests, no network or model calls."""
from __future__ import annotations
import os
from pathlib import Path
import pytest
from bonsai_g3_ab import SOURCES
from bonsai_g3_m1_guard import read_pinned_sources
from m5_offline_runner import audit_offline

ROOT=Path(__file__).resolve().parent
WF=ROOT/'.github/workflows/bonsai-g3-m5-offline-candidate.yml'

def test_workflow_manual_only():
    txt=WF.read_text(encoding='utf8')
    assert '\non:\n  workflow_dispatch:\n' in txt
    assert "if: ${{ github.event_name == 'workflow_dispatch' && github.actor == 'Hiderock61' }}" in txt
    assert 'permissions:\n  contents: read' in txt

@pytest.mark.parametrize('frag',[ 'issue_comment:', 'pull_request:', 'schedule:', 'on: push:',
                                 'secrets.', 'OPENAI_API_KEY', '--allow-billable',
                                 'actions/upload-artifact', 'gh api', 'actions/create-release'])
def test_workflow_forbids_live_triggers_and_secret_evidence(frag):
    txt=WF.read_text(encoding='utf8')
    # comments refer to excluded strings; ignore lines prefixed with #
    executable='\n'.join(line for line in txt.splitlines() if not line.lstrip().startswith('#'))
    assert frag not in executable

def test_workflow_requires_python311_and_only_pytest_dependency():
    txt=WF.read_text(encoding='utf8')
    assert "python-version: '3.11'" in txt
    assert "'pytest==9.0.2'" in txt
    assert 'pip install -r requirements.txt' not in txt
    assert 'python m5_offline_runner.py --require-python311' in txt
    assert 'python m5_summary_check.py' in txt

def test_read_only_pinned_sha_bytes():
    bundle=read_pinned_sources(ROOT/'g3/pinned_six',SOURCES)
    assert bundle.verified
    assert len(bundle.texts)==6
    assert sum(len(v.encode('utf8')) for v in bundle.texts.values())==76809

def test_runner_rejects_missing_explicit_offline_mode(monkeypatch):
    monkeypatch.delenv('BONSAI_G3_OFFLINE_MODE',raising=False)
    with pytest.raises(RuntimeError,match='MODE_HOLD'):
        audit_offline()

def test_runner_completes_local_independent_ab(monkeypatch):
    monkeypatch.setenv('BONSAI_G3_OFFLINE_MODE','offline_mock')
    r=audit_offline()
    assert r['status']=='LOCAL_OFFLINE_MOCK_PASS'
    assert r['model_api_calls']==r['browser_calls']==0
    assert r['t0_semantic_quality']=='UNKNOWN'
    assert r['two_independent_sessions']

def test_summary_rejects_forged_python311(monkeypatch,tmp_path):
    from m5_summary_check import check
    monkeypatch.setenv('BONSAI_G3_OFFLINE_MODE','offline_mock')
    r=audit_offline()
    r['python_311_execution']=False
    target=tmp_path/'report.json'
    import json
    target.write_text(json.dumps(r),encoding='utf8')
    assert not check(target)

def test_runner_holds_tampered_local_source(monkeypatch,tmp_path):
    # No mutation of originals. Copy a sacrificial local fixture only.
    import shutil
    from bonsai_g3_m1_guard import require_official_local_sources
    from bonsai_g3_transport import SourceHold
    clone=tmp_path/'s'
    shutil.copytree(ROOT/'g3/pinned_six',clone)
    target=clone/'BONSAI_START_HERE.md'
    target.write_bytes(target.read_bytes()+b'BAD')
    with pytest.raises(SourceHold):require_official_local_sources(clone)
