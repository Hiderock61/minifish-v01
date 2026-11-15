"""M2: verify actual local bytes against fixed public Git blob SHA manifest.
No external calls. No API, no user credentials.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha1, sha256
from pathlib import Path
import json
from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import read_pinned_sources,SourceHold

ROOT=Path(__file__).resolve().parent

def verify(root:Path):
    b=read_pinned_sources(root)
    report=[]
    for name,expect in SOURCES.items():
        contents=(root/name).read_bytes()
        independent_blob=sha1(f'blob {len(contents)}\0'.encode()+contents).hexdigest()
        assert independent_blob==expect
        report.append({'path':name,'bytes':len(contents),'git_blob_sha1':independent_blob,
                       'sha256':sha256(contents).hexdigest(),'verified':True,
                       'origin':('2026-09-13 archived BONSAI_PORTABLE exact-byte reconstruction' if name!='experiments/bonsai-performance-runtime-v0.1d-candidate.md' else 'connected GitHub source text reconstructed locally, exact byte sha verified')})
    # A canonical digest of all pathname/byte pairs in their fixed order
    agg=sha256()
    for f in report:
        contents=(root/f['path']).read_bytes()
        agg.update(len(f['path'].encode()).to_bytes(4,'big'))
        agg.update(f['path'].encode())
        agg.update(len(contents).to_bytes(8,'big'))
        agg.update(contents)
    return {'operation':'BONSaY_G3_M2_LOCAL_SOURCES','status':'LOCAL_SOURCE_6_OF_6_PASS',
            'created_at_utc':datetime.now(timezone.utc).isoformat(),
            'source_count':len(report),'total_source_bytes':sum(v['bytes'] for v in report),
            'combined_canonical_sha256':agg.hexdigest(), 'files':report,
            'model_calls':0,'official_token_count_calls':0,
            'live_authentication':'NOT_CHECKED','actual_semantic_ab':'UNKNOWN',
            'scope':'Local-byte verification only; no proof of AI read or independent model compatibility',
            'repo_writes':0,'notion_writes':0,'website_writes':0}

if __name__=='__main__':
    r=verify(ROOT/'pinned_six')
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence'/'m2_verified_six.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in r.items() if k!='files'},ensure_ascii=False,indent=2))
