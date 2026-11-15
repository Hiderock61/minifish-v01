from copy import deepcopy
from pathlib import Path
import pytest
from preflight_readonly import audit, modeled_cost, validate_receipts, SourceHold
import json

HERE=Path(__file__).parent
receipts=json.loads((HERE/'github_source_receipts.json').read_text(encoding='utf-8'))

def test_six_git_sha_receipts_match():
    s=validate_receipts(receipts); assert s['count']==6 and s['all_sha_matched']

def test_remote_source_bytes_are_exact_per_connector():
    assert validate_receipts(receipts)['sum_utf8_bytes']==76809

def test_forged_receipt_is_rejected():
    r=deepcopy(receipts);r['sources'][0]['sha']='0'*40
    with pytest.raises(SourceHold):validate_receipts(r)

def test_missing_source_is_rejected():
    r=deepcopy(receipts); r['sources'].pop()
    with pytest.raises(SourceHold):validate_receipts(r)

def test_offline_blocks_live_without_consent():
    assert audit(HERE)['live_with_no_explicit_consent_blocked'] is True

def test_total_request_count_and_source_bytes():
    r=audit(HERE); assert r['max_calls_total']==8
    assert r['min_source_body_bytes_sent_across_8_calls']==614472

def test_do_not_claim_local_source_pass():
    assert audit(HERE)['local_source_status']=='HOLD_LOCAL_FILES_NOT_PRESENT'

def test_cost_math_for_luna_scenario():
    r=modeled_cost(32000)
    assert r['assumed_total_input_tokens']==292000
    assert r['assumed_total_output_tokens']==24000
    assert r['usd_unbilled_scenario']==0.0412

def test_no_live_calls_made():
    r=audit(HERE); assert r['api_calls_made']==0 and r['live_run_status']=='HOLD'
