"""G3-M2 local materialization regression tests; no external/API calls."""
import os
import shutil
from pathlib import Path
import pytest
from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import read_pinned_sources, git_blob_sha, SourceHold
from stage_pinned_sources import stage_sources

HERE=Path(__file__).resolve().parents[1]
PINNED=HERE/'pinned_six'

def copy(src:Path, to:Path)->Path:
    shutil.copytree(src,to)
    return to

def test_01_complete_originals_from_bytes():
    bundle=read_pinned_sources(PINNED)
    assert bundle.verified
    assert len(bundle.texts)==6
    assert set(bundle.texts)==set(SOURCES)

def test_02_git_shas_rechecked_independently():
    for path,sha in SOURCES.items():
        assert git_blob_sha((PINNED/path).read_bytes())==sha

def test_03_utf8_actual_byte_total():
    assert sum(len((PINNED/k).read_bytes()) for k in SOURCES)==76809

def test_04_staging_proves_six_locally(tmp_path):
    dest=tmp_path/'verified'
    report=stage_sources(PINNED,dest)
    assert report['files']==6 and report['bytes']==76809
    assert read_pinned_sources(dest).verified

def test_05_existing_target_refused_without_change(tmp_path):
    dest=tmp_path/'exist';dest.mkdir();sentinel=dest/'keep';sentinel.write_text('unchanged')
    with pytest.raises(SourceHold,match='destination_already_exists'):
        stage_sources(PINNED,dest)
    assert sentinel.read_text()=='unchanged'

def test_06_changed_byte_blocks_atomic_stage(tmp_path):
    src=copy(PINNED,tmp_path/'src');dest=tmp_path/'new'
    p=src/'BONSAI_START_HERE.md';p.write_bytes(p.read_bytes()+b'evil')
    with pytest.raises(SourceHold,match='git_blob_mismatch'):
        stage_sources(src,dest)
    assert not dest.exists()

def test_07_missing_file_blocks_atomic_stage(tmp_path):
    src=copy(PINNED,tmp_path/'src');dest=tmp_path/'new'
    (src/'methods/006C_hideroko-injection-protocol.md').unlink()
    with pytest.raises(SourceHold,match='unavailable_or_unreadable_source'):
        stage_sources(src,dest)
    assert not dest.exists()

def test_08_symlink_leaf_refused(tmp_path):
    src=copy(PINNED,tmp_path/'src')
    p=src/'BONSAI_START_HERE.md'
    target=tmp_path/'normal';target.write_bytes(p.read_bytes())
    p.unlink();p.symlink_to(target)
    with pytest.raises(SourceHold,match='source_symlink_refused'):
        read_pinned_sources(src)

def test_09_manifest_wrong_path_set_refused():
    wrong={k:v for k,v in SOURCES.items() if k!='BONSAI_START_HERE.md'}
    with pytest.raises(SourceHold,match='source_manifest_path_set_mismatch'):
        read_pinned_sources(PINNED,wrong)

def test_10_independent_copy_does_not_mutate_source(tmp_path):
    before={k:(PINNED/k).read_bytes() for k in SOURCES}
    dest=tmp_path/'new'
    stage_sources(PINNED,dest)
    assert {k:(PINNED/k).read_bytes() for k in SOURCES}==before

def test_11_target_symlink_is_refused(tmp_path):
    dest=tmp_path/'link'
    dest.symlink_to(PINNED,target_is_directory=True)
    with pytest.raises(SourceHold,match='destination_already_exists'):
        stage_sources(PINNED,dest)

def test_12_unmodified_m1_preflight_recognizes_materialized_sources():
    # Same code path that previously yielded LOCAL_SOURCE_HOLD now verifies all bytes.
    bundle=read_pinned_sources(PINNED)
    assert sum(len(v.encode('utf-8')) for v in bundle.texts.values()) == 76809
