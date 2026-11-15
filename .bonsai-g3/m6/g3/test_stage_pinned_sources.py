from pathlib import Path
import pytest
from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import SourceHold, git_blob_sha, read_pinned_sources
from stage_pinned_sources import stage_sources


def make_synthetic_checkout(root):
    manifest={}
    for path in SOURCES:
        f=root/path
        f.parent.mkdir(parents=True,exist_ok=True)
        data=(f'SYNTHETIC DEMO; not original: {path}\n').encode('utf-8')
        f.write_bytes(data)
        manifest[path]=git_blob_sha(data)
    return manifest


def test_atomic_stage_synthetic_files_without_network(tmp_path):
    src=tmp_path/'source'
    manifest=make_synthetic_checkout(src)
    dest=tmp_path/'staged'
    d=stage_sources(src,dest,manifest)
    assert d['status']=='SIX_LOCAL_FILES_STAGED'
    assert d['files']==6
    assert read_pinned_sources(dest,manifest).verified
    assert all((src/p).read_bytes()==(dest/p).read_bytes() for p in SOURCES)


def test_stage_refuses_invalid_original_before_creating_target(tmp_path):
    src=tmp_path/'source'
    manifest=make_synthetic_checkout(src)
    (src/'BONSAI_START_HERE.md').write_text('tampered')
    dest=tmp_path/'staged'
    with pytest.raises(SourceHold,match='git_blob_mismatch'):
        stage_sources(src,dest,manifest)
    assert not dest.exists()


def test_stage_does_not_overwrite_existing_dir(tmp_path):
    src=tmp_path/'source'
    manifest=make_synthetic_checkout(src)
    dest=tmp_path/'staged'
    dest.mkdir()
    (dest/'owner_file.txt').write_text('untouched')
    with pytest.raises(SourceHold,match='destination_already_exists'):
        stage_sources(src,dest,manifest)
    assert (dest/'owner_file.txt').read_text()=='untouched'


def test_stage_refuses_symlink_escape(tmp_path):
    src=tmp_path/'source'
    manifest=make_synthetic_checkout(src)
    f=src/'BONSAI_START_HERE.md'
    target=src/'linked-real.md'
    target.write_bytes(f.read_bytes())
    f.unlink()
    f.symlink_to(target)
    with pytest.raises(SourceHold,match='source_symlink_refused'):
        stage_sources(src,tmp_path/'dest',manifest)
    assert not (tmp_path/'dest').exists()
