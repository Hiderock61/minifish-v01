"""Print only a constant, compact verdict from an allowlisted mock summary."""
from __future__ import annotations
import json
import sys
from pathlib import Path

def check(path:Path)->bool:
    obj=json.loads(path.read_text(encoding='utf8'))
    return (
        obj.get('status')=='LOCAL_OFFLINE_MOCK_PASS'
        and obj.get('source_status')=='LOCAL_SOURCE_6_OF_6_PASS'
        and obj.get('source_bytes')==76809
        and obj.get('model_api_calls')==0
        and obj.get('official_token_counter_api_calls')==0
        and obj.get('live_model_ab')=='NOT_TESTED'
        and obj.get('t0_semantic_quality')=='UNKNOWN'
        and obj.get('python_311_execution') is True
        and obj.get('conditions',{}).get('A',{}).get('generations')==3
        and obj.get('conditions',{}).get('B',{}).get('generations')==3
    )

if __name__=='__main__':
    if len(sys.argv)!=2 or not check(Path(sys.argv[1])):
        print('BONSaY_G3_M5_HOLD',file=sys.stderr)
        raise SystemExit(2)
    print('BONSaY_G3_M5_ACTIONS_OFFLINE_MOCK_PASS (not live model; semantics UNKNOWN)')
