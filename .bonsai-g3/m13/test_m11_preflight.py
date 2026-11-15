from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal
from shutil import copytree
import json
import pytest
from m11_preflight import snapshot,cost_usd
from m11_quality_audit import blank_sheet,validate_sheet,ReviewHold,FIELDS,FATAL

ROOT=Path(__file__).resolve().parent

@pytest.fixture(scope='module')
def result():return snapshot(ROOT/'pinned_six')

def test_source_6_exact(result):
    assert result['source_count_verified']==6
    assert result['source_bytes_verified']==76809
    assert result['six_git_blob_sha_matched'] is True

def test_a_input_reuses_recorded_hash(result):
    a=result['conditions']['A'];assert a['input_utf8_bytes']==80429
    assert a['input_sha256']=='104c85d049e71ee9af4b5fdfcd088d86f9498b014a3eba612cd44bc53a316760'

def test_b_input_reuses_recorded_hash(result):
    b=result['conditions']['B'];assert b['input_utf8_bytes']==80989
    assert b['input_sha256']=='114aae0f0d3e357e8e8773139ee4116b6e6e34e279a3d3b1cb882b2b0780fd1d'

def test_8max_reservation_over_5cent_cap(result):
    assert result['cost_worst_case_usd']=='0.052'
    assert result['full_8_call_completion_guaranteed_by_local_cap'] is False
    assert result['max_input_tokens_total_for_worst_case_within_current_cap']==380000

def test_max_per_request_price_and_cap(result):
    assert cost_usd(50_000,3000,Decimal('.1'),Decimal('.5'))==Decimal('.0065')

def test_conservative_holds(result):
    assert result['readiness']=='LIVE_HOLD'
    assert 'SDK_RETRIES_MUST_BE_FORCED_TO_ZERO' in result['independent_holds']
    assert result['official_input_token_count']=='UNKNOWN_NOT_CALLED'

def test_no_network_or_secrets(result):
    assert result['api_requests_executed']==0
    assert result['github_writes_executed']==0
    assert result['authenticated_reads_executed']==0
    assert result['model_api_authorization']=='NOT_GRANTED'

def test_source_tamper_is_refused():
    from bonsai_g3_transport import SourceHold
    with TemporaryDirectory() as d:
        root=Path(d)/'six';copytree(ROOT/'pinned_six',root)
        p=root/'BONSAI_START_HERE.md';p.write_bytes(p.read_bytes()+b'X')
        with pytest.raises(SourceHold):snapshot(root)

def test_missing_source_is_refused():
    from bonsai_g3_transport import SourceHold
    with TemporaryDirectory() as d:
        root=Path(d)/'six';copytree(ROOT/'pinned_six',root)
        (root/'BONSAI_START_HERE.md').unlink()
        with pytest.raises(SourceHold):snapshot(root)

def test_blank_review_is_hold():
    with pytest.raises(ReviewHold):validate_sheet(blank_sheet())

def test_blinded_sheet_with_evidence_can_validate_but_never_proves_superiority():
    x=blank_sheet()
    for rows in x['grades'].values():
        for row in rows:
            row['scores']={field:1 for field in FIELDS}
            row['fatal']={field:False for field in FATAL}
            row['evidence_note']='Reviewed source text with original T0.'
            row['route_labels_masked']=True
    res=validate_sheet(x)
    assert res['generalizable_superiority']=='NOT_ESTABLISHED'
    assert res['substantive_improvement'].startswith('UNKNOWN')

def test_fake_claim_as_score_is_hold():
    x=blank_sheet()
    for rows in x['grades'].values():
        for row in rows:
            row['scores']={field:1 for field in FIELDS}
            row['fatal']={field:False for field in FATAL}
            row['evidence_note']='Required independent reason.'
            row['route_labels_masked']=True
    x['grades']['Y'][1]['scores']['t0_substantive_link']=True
    with pytest.raises(ReviewHold):validate_sheet(x)

def test_unmasked_label_is_hold():
    x=blank_sheet()
    for rows in x['grades'].values():
        for row in rows:
            row['scores']={field:1 for field in FIELDS}
            row['fatal']={field:False for field in FATAL}
            row['evidence_note']='Observed note'
            row['route_labels_masked']=True
    x['grades']['X'][0]['route_labels_masked']=False
    with pytest.raises(ReviewHold):validate_sheet(x)

def test_static_preflight_never_imports_sdk():
    source=(ROOT/'m11_preflight.py').read_text()
    assert 'import openai' not in source
    assert 'from openai import ' not in source
    assert 'OPENAI_API_KEY' not in source
    assert 'requests.post(' not in source

def test_readiness_cannot_be_pass_by_template():
    assert snapshot(ROOT/'pinned_six')['readiness']=='LIVE_HOLD'
