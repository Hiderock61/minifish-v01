"""Verify every byte against the frozen M5 SHA256 manifest before M6 PR mock QA."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

class IntegrityHold(Exception):
    pass

def check_manifest(root: Path, manifest: Path) -> dict:
    root=root.resolve(strict=True)
    if manifest.is_symlink() or not manifest.is_file():
        raise IntegrityHold('manifest_file_missing_or_symlink')
    data=json.loads(manifest.read_text(encoding='utf-8'))
    items=data.get('items')
    if type(items) is not list or len(items)!=31 or data.get('file_count')!=31:
        raise IntegrityHold('unexpected_manifest_count')
    seen=set()
    for entry in items:
        name=entry.get('path','')
        p=PurePosixPath(name)
        if not name or p.is_absolute() or '..' in p.parts or str(p)!=name or name in seen:
            raise IntegrityHold('unsafe_or_duplicate_path')
        seen.add(name)
        target=root.joinpath(*p.parts)
        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root):
            raise IntegrityHold('missing_or_symlink_source')
        raw=target.read_bytes()
        if len(raw)!=entry.get('bytes') or hashlib.sha256(raw).hexdigest()!=entry.get('sha256'):
            raise IntegrityHold('m5_sha_or_size_mismatch')
    return {'status':'M5_31_OF_31_SAME_BYTES','checked_files':31}

if __name__=='__main__':
    try:
        loc=Path(sys.argv[1]) if len(sys.argv)==2 else Path('evidence/m5_file_sha256_manifest.json')
        d=check_manifest(Path(__file__).resolve().parent,loc)
        print(d['status'])
    except (IntegrityHold, KeyError, ValueError, OSError, json.JSONDecodeError):
        print('BONSaY_M6_SOURCE_HOLD',file=sys.stderr)
        raise SystemExit(2)
