"""BONSaY G3 M5: strict offline-only CI mock adapter. No SDK/network/browser."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'g3'))
from bonsai_g3_m1_guard import (default_offline_ledger,run_checked_pair,
                                require_official_local_sources)
from bonsai_g3_transport import TransportSettings
from bonsai_g3_ab import SOURCES

def audit_offline(*, require_python311=False):
    if os.getenv('BONSAI_G3_OFFLINE_MODE')!='offline_mock':
        raise RuntimeError('MODE_HOLD_EXPECTED_OFFLINE_MOCK')
    if require_python311 and sys.version_info[:2]!=(3,11):
        raise RuntimeError('PYTHON311_RUNTIME_REQUIRED')
    # Exact pinned bytes before creating even a mock session.
    source_root=HERE/'g3/pinned_six'
    b=require_official_local_sources(source_root)
    source_bytes=sum(len(b.texts[p].encode('utf-8')) for p in SOURCES)
    if source_bytes!=76809 or len(b.texts)!=6:
        raise RuntimeError('SOURCE_SIZE_OR_COUNT_MISMATCH')
    ledger=default_offline_ledger()
    settings=TransportSettings(model=ledger.price.model,mode='offline_mock',
                               allow_billable=False, output_tokens=3000)
    with tempfile.TemporaryDirectory(prefix='bonsai-m5-fixture-') as d:
        r=run_checked_pair(source_root=source_root, client_factory=None,
                           settings=settings, ledger=ledger,private_dir=Path(d)/'private')
        # Synthetic transcript files are intentionally deleted when d closes.
        for c in ('A','B'):
            q=r[c]
            if q['status']!='DELIVERY_COMPLETE_AUDIT_PENDING':
                raise RuntimeError('MOCK_SESSION_HOLD_'+c)
            if q['completed_generations']!=3 or q['calls']!=4:
                raise RuntimeError('MOCK_TURN_COUNT_MISMATCH_'+c)
            if q['semantic_status']!='UNKNOWN_NOT_INDEPENDENTLY_EVALUATED':
                raise RuntimeError('SEMANTIC_VERDICT_MUST_REMAIN_UNKNOWN')
        if not r['independent_client_instances'] or ledger.calls_submitted!=8:
            raise RuntimeError('A_B_SESSION_OR_BUDGET_NOT_INDEPENDENT')
        if ledger.frozen or ledger.last_hold_reason is not None:
            raise RuntimeError('MOCK_LEDGER_HOLD')
        if r['M1_local_sources']!='VERIFIED_6_BLOBS':
            raise RuntimeError('LOCAL_SOURCE_NOT_VERIFIED')
    return {
        'phase':'BONSaY_G3_M5_OFFLINE_ACTIONS_CANDIDATE',
        'status':'LOCAL_OFFLINE_MOCK_PASS',
        'python_actual':'.'.join(map(str,sys.version_info[:3])),
        'python_311_execution': sys.version_info[:2]==(3,11),
        'source_status':'LOCAL_SOURCE_6_OF_6_PASS',
        'source_bytes':source_bytes,
        'source_expected_blob_sha':dict(SOURCES),
        'conditions':{'A':{'generations':3,'calls':4,'status':'MOCK_ONLY'},
                      'B':{'generations':3,'calls':4,'status':'MOCK_ONLY'}},
        'two_independent_sessions':True,
        'shared_budget_ledger':True,
        'token_count':'OFFLINE_SYNTHETIC_ONLY',
        'model_api_calls':0,
        'official_token_counter_api_calls':0,
        'browser_calls':0,
        'external_writes':0,
        'live_model_ab':'NOT_TESTED',
        't0_semantic_quality':'UNKNOWN',
        'github_actions_run':'NOT_EXECUTED_BY_THIS_TOOL',
        'billing':'MODEL_API_ZERO_GITHUB_ACTIONS_MINUTES_NOT_FREE_GUARANTEE',
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--require-python311',action='store_true')
    parser.add_argument('--out',type=Path,default=Path('m5_public_summary.json'))
    args=parser.parse_args()
    try:
        report=audit_offline(require_python311=args.require_python311)
        # Public-safe summary only; exclude model prompts and transcripts.
        if args.out.is_symlink() or args.out.exists():
            raise RuntimeError('REPORT_OUTPUT_ALREADY_EXISTS_OR_SYMLINK')
        args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('BONSaY_G3_M5_LOCAL_MOCK_PASS: 6 sources; A/B 3+3 generations; 8 synthetic turns; model API calls=0')
    except Exception as e:
        # Never print SDK error text or any untrusted exception details.
        print('BONSaY_G3_M5_HOLD: '+type(e).__name__,file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__':main()
