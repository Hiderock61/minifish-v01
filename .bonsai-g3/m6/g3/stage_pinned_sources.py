"""Offline exact-byte import of the six immutable BONSaY source files.

Requires a caller-supplied local repository checkout. Does not use network,
connectors or API keys. Never alters the supplied source directory.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import mkdtemp
from typing import Mapping
import argparse
import os
import shutil
import stat

from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import SourceHold, read_pinned_sources


def stage_sources(src: Path, target: Path,
                  manifest: Mapping[str, str] = SOURCES) -> dict:
    """Full precheck then atomic publish. Fail if destination already exists."""
    source = Path(src).resolve(strict=True)
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise SourceHold('destination_already_exists_refuse_overwrite')
    bundle = read_pinned_sources(source, manifest)
    parent = target.parent.resolve(strict=True)
    temp = Path(mkdtemp(prefix='bonsai-staging-', dir=parent))
    try:
        temp.chmod(0o700)
        for rel in bundle.texts:
            path = temp / rel
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes((source / rel).read_bytes())
            path.chmod(0o600)
        recheck = read_pinned_sources(temp, manifest)
        if not recheck.verified:
            raise SourceHold('second_verification_failed')
        # os.replace is atomic only on the same filesystem and when target absent.
        # Temporary directory and destination have the same parent.
        if target.exists() or target.is_symlink():
            raise SourceHold('destination_race_refuse_overwrite')
        os.rename(temp, target)
        return {'status':'SIX_LOCAL_FILES_STAGED', 'files':len(recheck.texts),
                'bytes':sum(len(v.encode('utf-8')) for v in recheck.texts.values()),
                'local_dir':str(target),
                'note':'Source-byte verification, NOT model-read proof'}
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main():
    p=argparse.ArgumentParser(description='Verify+stage exact BONSaY six Git blobs from a local checkout')
    p.add_argument('--from-checkout',type=Path,required=True)
    p.add_argument('--to-dir',type=Path,required=True)
    args=p.parse_args()
    print(stage_sources(args.from_checkout,args.to_dir))


if __name__=='__main__':
    main()
