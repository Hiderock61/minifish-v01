"""M13 read-only verification of M12 frozen originals before Python3.11 QA."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parent
def verify() -> None:
    manifest=ROOT/'M12_SHA256_MANIFEST.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError('M13_MANIFEST_UNKNOWN')
    data=json.loads(manifest.read_text(encoding='utf-8'))
    items=data.get('sha256_items')
    if type(items) is not list or len(items)!=23 or data.get('count')!=23:
        raise RuntimeError('M13_BAD_MANIFEST_COUNT')
    seen=set()
    for entry in items:
        name=entry['path'];parts=PurePosixPath(name)
        if not isinstance(name,str) or parts.is_absolute() or '..' in parts.parts or str(parts)!=name or name in seen:
            raise RuntimeError('M13_BAD_PATH')
        seen.add(name)
        source=ROOT.joinpath(*parts.parts)
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(ROOT):
            raise RuntimeError('M13_SOURCE_MISSING_OR_LINK')
        b=source.read_bytes()
        if len(b)!=entry.get('bytes') or hashlib.sha256(b).hexdigest()!=entry.get('sha256'):
            raise RuntimeError('M13_SOURCE_CHANGED')
    # The manifest itself and every frozen M12 file must be present, with no extra M12 placeholders.
    if len(seen | {'M12_SHA256_MANIFEST.json'})!=24:
        raise RuntimeError('M13_FROZEN_COUNT')
    print('BONSaY_M13_FROZEN_M12_24_OF_24_PRESENT_23_SHA_VERIFIED')

if __name__=='__main__':
    verify()
