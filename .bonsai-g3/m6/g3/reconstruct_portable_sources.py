"""Recover five exact Git blobs from user's archived portable, strictly pinned to expected SHA.

No source repository modification. Reject any unavailable or incorrect source.
"""
from __future__ import annotations
import re
from pathlib import Path
from tempfile import mkdtemp
import shutil
from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import git_blob_sha,SourceHold


def extract_portable_five(portable: Path, output:Path):
    text=portable.read_text(encoding='utf8')
    markers=list(re.finditer(r'^# SOURCE FILE: `([^`]+)`\n',text,re.M))
    if len(markers)!=5:
        raise SourceHold('portable_section_count_not_five')
    if output.exists() or output.is_symlink():
        raise SourceHold('output_already_exists')
    # Reconstruct only if SHA independently matches expected. Do not guess omitted data.
    tmp=Path(mkdtemp(dir=output.parent,prefix='m2-five-temp-'))
    try:
        tmp.chmod(0o700)
        receipts=[]
        for i,m in enumerate(markers):
            rel=m.group(1)
            if rel not in SOURCES:
                raise SourceHold('unexpected_source_section')
            raw=text[m.end():markers[i+1].start() if i+1<len(markers) else len(text)]
            # Portable generator inserted an initial line break and a boundary separator.
            # Git blob hash is authority. Do not accept approximate matches.
            options=[]
            for leading in range(3):
                for trailing in range(10):
                    for add in range(3):
                        candidate=(raw[leading:len(raw)-trailing if trailing else None] + '\n'*add).encode('utf8')
                        if git_blob_sha(candidate)==SOURCES[rel]: options.append(candidate)
            unique=list(set(options))
            if len(unique)!=1:
                raise SourceHold(f'unique_sha_reconstruction_failed:{rel}:{len(unique)}')
            dest=tmp/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(unique[0]);dest.chmod(0o600)
            receipts.append({'path':rel,'bytes':len(unique[0]),'blob_sha':git_blob_sha(unique[0]),'status':'PASS_FROM_PORTABLE'})
        if len(receipts)!=5 or {v['path'] for v in receipts}!={k for k in SOURCES if k!='experiments/bonsai-performance-runtime-v0.1d-candidate.md'}:
            raise SourceHold('wrong_source_set')
        tmp.rename(output)
        return receipts
    finally:
        if tmp.exists(): shutil.rmtree(tmp)

if __name__=='__main__':
    import argparse,json
    ap=argparse.ArgumentParser()
    ap.add_argument('--portable',type=Path,required=True,
                    help='Path to archived BONSAI_PORTABLE_v0.5.md supplied by owner')
    ap.add_argument('--out-dir',type=Path,required=True,
                    help='New destination for exactly five source files; must not exist')
    a=ap.parse_args()
    print(json.dumps(extract_portable_five(a.portable,a.out_dir),ensure_ascii=False,indent=2))
