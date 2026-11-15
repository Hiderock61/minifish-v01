"""M6 offline-only PR label trigger static contract tests. No network actions."""
from pathlib import Path
import json
import shutil
import pytest
from m6_integrity_check import check_manifest, IntegrityHold

ROOT=Path(__file__).resolve().parent
M6=ROOT/'.github/workflows/bonsai-g3-m6-draft-review.yml'
M5=ROOT/'.github/workflows/bonsai-g3-m5-offline-candidate.yml'
BASE='f16a39043111d0de224e793b43ab6917780a02f9'

def functional():
    return '\n'.join(l for l in M6.read_text(encoding='utf-8').splitlines() if not l.lstrip().startswith('#'))

def test_m5_original_workflow_retained_unchanged():
    assert 'workflow_dispatch:' in M5.read_text(encoding='utf-8')
    assert check_manifest(ROOT,ROOT/'evidence/m5_file_sha256_manifest.json')['checked_files']==31

def test_m6_only_label_event():
    w=functional()
    assert '\non:\n  pull_request:\n    types: [labeled]\n' in w
    assert 'workflow_dispatch:' not in w
    assert 'push:' not in w
    assert 'issue_comment:' not in w
    assert 'schedule:' not in w

def test_owner_label_exact_name():
    w=functional()
    assert "github.event.label.name == 'bonsai-g3-m6-run-approved'" in w
    assert "github.actor == 'Hiderock61'" in w
    assert "github.event.pull_request.user.login == 'Hiderock61'" in w
    assert "github.event.action == 'labeled'" in w

def test_branch_and_source_repo_exact():
    w=functional()
    assert "github.event.pull_request.head.ref == 'review/bonsai-g3-m6-20261115'" in w
    assert "github.event.pull_request.head.repo.full_name == 'Hiderock61/minifish-v01'" in w
    assert "github.event.pull_request.base.repo.full_name == 'Hiderock61/minifish-v01'" in w

def test_base_main_head_fixed():
    w=functional()
    assert "github.event.pull_request.base.ref == 'main'" in w
    assert "github.event.pull_request.base.sha == '"+BASE+"'" in w
    assert 'github.event.pull_request.head.sha' in w

def test_draft_pr_only():
    assert 'github.event.pull_request.draft == true' in functional()

def test_minimum_permissions():
    w=functional()
    assert 'permissions:\n  contents: read' in w
    assert 'contents: write' not in w
    assert 'issues: write' not in w

def test_python_311_and_fail_closed_summary():
    w=functional()
    assert "python-version: '3.11'" in w
    assert 'python m5_offline_runner.py --require-python311' in w
    assert 'python m5_summary_check.py m6_public_summary.json' in w

def test_no_secrets_live_sdk_or_upload():
    w=functional()
    for k in ['secrets.', 'OPENAI_API_KEY', 'OPENAI_MODEL', '--allow-billable',
              'pip install -r requirements.txt', 'actions/upload-artifact',
              'gh api', 'pull_request_target', 'repository_dispatch', 'curl ',
              'actions/cache', 'create_issue', 'gh issue']:
        assert k not in w

def test_original_contents_pinned_before_execution():
    w=functional()
    assert 'python m6_integrity_check.py evidence/m5_file_sha256_manifest.json' in w
    assert w.index('python m6_integrity_check.py') < w.index('python -m pytest')
    assert w.index('python -m pytest') < w.index('python m5_offline_runner.py')

def test_no_token_or_transcript_publication():
    w=functional()
    assert 'upload-artifact' not in w
    assert 'persist-credentials: false' in w
    assert "python -m pip install --disable-pip-version-check 'pytest==9.0.2'" in w

def test_manifest_rejects_mutated_fixture(tmp_path):
    d=tmp_path/'case'
    d.mkdir()
    shutil.copytree(ROOT/'g3',d/'g3')
    shutil.copytree(ROOT/'.github',d/'.github')
    shutil.copytree(ROOT/'evidence',d/'evidence')
    shutil.copy2(ROOT/'README.md',d/'README.md')
    shutil.copy2(ROOT/'m5_offline_runner.py',d/'m5_offline_runner.py')
    shutil.copy2(ROOT/'m5_summary_check.py',d/'m5_summary_check.py')
    shutil.copy2(ROOT/'test_m5_contract.py',d/'test_m5_contract.py')
    shutil.copy2(ROOT/'manifest.json',d/'manifest.json')
    p=d/'g3/pinned_six/BONSAI_START_HERE.md'
    p.write_bytes(p.read_bytes()+b'M6 BAD')
    with pytest.raises(IntegrityHold):
        check_manifest(d,d/'evidence/m5_file_sha256_manifest.json')

def test_manifest_missing_file_holds(tmp_path):
    data=json.loads((ROOT/'evidence/m5_file_sha256_manifest.json').read_text())
    dummy=tmp_path/'dummy';dummy.mkdir()
    (dummy/'manifest.json').write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(IntegrityHold):
        check_manifest(dummy,dummy/'manifest.json')

def test_no_m6_deployment_evidence():
    readme=(ROOT/'README_M6.md').read_text(encoding='utf-8')
    assert 'NOT_DEPLOYED' in readme
    assert 'ACTIONS_RUN_NOT_EXECUTED' in readme

def test_source_blob_count():
    from bonsai_g3_m1_guard import require_official_local_sources
    from bonsai_g3_ab import SOURCES
    s=require_official_local_sources(ROOT/'g3/pinned_six')
    assert len(s.texts)==len(SOURCES)==6
    assert sum(len(t.encode('utf-8')) for t in s.texts.values())==76809
