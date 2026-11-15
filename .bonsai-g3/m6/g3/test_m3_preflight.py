from decimal import Decimal
from pathlib import Path
import pytest
from m3_preflight import audit, cost_at_cap, sdk_metadata

HERE = Path(__file__).resolve().parent

def test_six_blobs_and_bytes():
    x=audit(HERE/'pinned_six')
    assert x['local_source_status']=='6_OF_6_PASS'
    assert x['local_source_bytes']==76809

def test_first_request_schema_and_size():
    x=audit(HERE/'pinned_six')
    assert set(x['first_request'])=={'A','B'}
    assert all(c['under_900000_byte_ceiling'] for c in x['first_request'].values())

def test_b_is_different_start_input():
    x=audit(HERE/'pinned_six')
    assert x['first_request']['A']['request_sha256'] != x['first_request']['B']['request_sha256']

def test_no_token_count_evidence_fabricated():
    x=audit(HERE/'pinned_six')
    assert x['official_input_tokens']=='UNKNOWN_NOT_CALLED'
    assert x['model_requests']==x['official_count_requests']==0

def test_no_credentials_introspection():
    x=audit(HERE/'pinned_six')
    assert x['credential_reads']==0
    assert x['key_validity']=='UNKNOWN_NOT_INSPECTED'

def test_no_billable_consent_from_go_a():
    assert audit(HERE/'pinned_six')['owner_approval_for_paid_network_requests'] is False

def test_price_single_cap():
    assert cost_at_cap(50000,3000)==Decimal('0.0065')

def test_price_max_all_exceeds_budget():
    assert cost_at_cap(400000,24000)==Decimal('0.052')
    assert audit(HERE/'pinned_six')['budget']['max_eight_requests_within_app_cap'] is False

def test_invalid_cost_fields_fail_closed():
    for a,b in [(-1,1),(1,-1),(1.5,1),(True,100)]:
        with pytest.raises(ValueError):cost_at_cap(a,b)

def test_sdk_status_is_discrete():
    assert sdk_metadata()['status'] in {'SDK_NOT_AVAILABLE','SDK_INSTALLED_NOT_AUTHENTICATED'}

def test_final_state_hold():
    assert audit(HERE/'pinned_six')['live_readiness']=='HOLD'

def test_missing_blob_fails_closed(tmp_path):
    with pytest.raises(Exception): audit(tmp_path)
