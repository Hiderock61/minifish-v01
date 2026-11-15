"""G3-M1 non-network safety tests; includes failure-injection paths."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from bonsai_g3_m1_guard import (
    SpendLedger, SpendHold, FrozenPrice, Limits, TokenCountReceipt,
    GuardedClient, OfflineTestCounter, default_offline_ledger,
    inspect_local_sources, require_official_local_sources, run_checked_pair,
    payload_digest,
)
from bonsai_g3_transport import SourceHold, TransportSettings, ExecutionHold, git_blob_sha, read_pinned_sources
from bonsai_g3_ab import SOURCES

REQ = {'model':'gpt-6-luna', 'input':[{'role':'user','content':'private question'}],
       'max_output_tokens':1000, 'store':False}


class FakeClient:
    def __init__(self, fail=False, status='completed', usage=True,
                 actual_input=1500, actual_output=300):
        self.calls=[]
        self.fail=fail
        self.status=status
        self.want_usage=usage
        self.actual_input=actual_input
        self.actual_output=actual_output
        self.responses=self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise Exception('secret PRIVATE_TOKEN abcdef')
        usage=SimpleNamespace(input_tokens=self.actual_input,
                              output_tokens=self.actual_output) if self.want_usage else None
        return SimpleNamespace(status=self.status, output_text='READY', usage=usage)


def call(ledger=None, client=None, req=None):
    ledger=ledger or default_offline_ledger()
    client=client or FakeClient()
    return ledger, client, lambda: GuardedClient(client, ledger).responses.create(**dict(req or REQ))


def test_budget_one_call_usage_and_receipt():
    ledger, client, act=call()
    response=act()
    assert response.output_text=='READY'
    assert client.calls==[REQ]
    assert ledger.calls_submitted==1
    assert ledger.input_tokens_counted==1500
    assert ledger.output_tokens_observed==300
    assert ledger.estimated_spent_usd==Decimal('0.00030')
    assert ledger.uncertain_reserved_usd==0
    assert ledger.receipts[0]['count_method']=='offline_simulation'


def test_shared_budget_two_clients():
    ledger=default_offline_ledger()
    a,b=FakeClient(),FakeClient()
    GuardedClient(a,ledger).create(**REQ)
    GuardedClient(b,ledger).create(**REQ)
    assert ledger.calls_submitted==2
    assert len(a.calls)==len(b.calls)==1


def test_no_send_when_count_service_fails():
    class BadCounter:
        def count(self, request): raise RuntimeError('internal secret')
    ledger=default_offline_ledger(counter=BadCounter())
    ledger,client,act=call(ledger=ledger)
    with pytest.raises(SpendHold,match='TOKEN_COUNT_UNAVAILABLE'): act()
    assert client.calls==[]
    assert ledger.frozen
    assert 'internal secret' not in json.dumps(ledger.public_status())


def test_receipt_digest_must_match_exact_request():
    class WrongDigest:
        def count(self, req): return TokenCountReceipt(req['model'],'0'*64,100,'offline_simulation')
    ledger=default_offline_ledger(counter=WrongDigest())
    ledger,client,act=call(ledger=ledger)
    with pytest.raises(SpendHold,match='TOKEN_COUNT_RECEIPT_INVALID'): act()
    assert not client.calls


def test_boolean_count_not_accepted():
    class BoolCounter:
        def count(self,req):return TokenCountReceipt(req['model'],payload_digest(req),True,'offline_simulation')
    ledger,client,act=call(default_offline_ledger(counter=BoolCounter()))
    with pytest.raises(SpendHold,match='TOKEN_COUNT_RECEIPT_INVALID'): act()
    assert not client.calls


def test_unverified_mock_count_cannot_authorize_live():
    base=default_offline_ledger()
    live=SpendLedger('live',base.price,base.limits,OfflineTestCounter())
    ledger,client,act=call(live)
    with pytest.raises(SpendHold,match='OFFICIAL_EXACT_TOKEN_COUNT_REQUIRED'): act()
    assert not client.calls


def test_price_model_mismatch_blocked():
    ledger,client,act=call(req={**REQ,'model':'another-model'})
    with pytest.raises(SpendHold,match='MODEL_PRICE_MISMATCH'): act()
    assert not client.calls


def test_store_true_blocked():
    ledger,client,act=call(req={**REQ,'store':True})
    with pytest.raises(SpendHold,match='STORE_MUST_BE_FALSE'): act()
    assert not client.calls


def test_extra_request_properties_unapproved():
    ledger,client,act=call(req={**REQ,'tools':[{'type':'web_search'}]})
    with pytest.raises(SpendHold,match='REQUEST_SCHEMA_MISMATCH'): act()
    assert not client.calls


def test_output_ceiling_blocked_before_count():
    ledger,client,act=call(req={**REQ,'max_output_tokens':4000})
    with pytest.raises(SpendHold,match='OUTPUT_CEILING_EXCEEDED'): act()
    assert not client.calls


def test_single_input_token_cap():
    base=default_offline_ledger()
    limits=Limits(1499,400000,3000,8,Decimal('0.05'))
    ledger=SpendLedger('offline_mock',base.price,limits,OfflineTestCounter())
    ledger,client,act=call(ledger)
    with pytest.raises(SpendHold,match='SINGLE_CALL_INPUT_TOKEN_CAP'): act()
    assert not client.calls


def test_cumulative_input_token_cap():
    base=default_offline_ledger()
    limits=Limits(5000,2000,3000,8,Decimal('0.05'))
    ledger=SpendLedger('offline_mock',base.price,limits,OfflineTestCounter())
    c=FakeClient()
    GuardedClient(c,ledger).create(**REQ)
    with pytest.raises(SpendHold,match='TOTAL_INPUT_TOKEN_CAP'):
        GuardedClient(c,ledger).create(**REQ)
    assert len(c.calls)==1


def test_pre_send_spend_cap_blocks_call():
    base=default_offline_ledger()
    limits=Limits(5000,10000,3000,8,Decimal('0.0003'))
    ledger=SpendLedger('offline_mock',base.price,limits,OfflineTestCounter())
    ledger,client,act=call(ledger)
    with pytest.raises(SpendHold,match='PRE_SEND_ESTIMATED_SPEND_CAP'): act()
    assert not client.calls


def test_budget_cap_blocks_second_call_not_first():
    base=default_offline_ledger()
    # reserve per 1500 input / 1000 output = 0.00065; observed 0.00030
    # a 0.00080 cap allows first, not second (0.00030 + 0.00065)
    limits=Limits(5000,10000,3000,8,Decimal('0.00080'))
    ledger=SpendLedger('offline_mock',base.price,limits,OfflineTestCounter())
    c=FakeClient()
    GuardedClient(c,ledger).create(**REQ)
    with pytest.raises(SpendHold,match='PRE_SEND_ESTIMATED_SPEND_CAP'):
        GuardedClient(c,ledger).create(**REQ)
    assert len(c.calls)==1


def test_eight_call_cap():
    ledger=default_offline_ledger()
    c=FakeClient()
    gc=GuardedClient(c,ledger)
    for _ in range(8):gc.create(**REQ)
    with pytest.raises(SpendHold,match='TOTAL_CALL_CAP_REACHED'):gc.create(**REQ)
    assert len(c.calls)==8


def test_transport_exception_reserved_and_no_retry():
    ledger,client,act=call(client=FakeClient(fail=True))
    with pytest.raises(SpendHold,match='MODEL_TRANSPORT_UNKNOWN_NO_RETRY'):act()
    assert len(client.calls)==1 and ledger.frozen
    assert ledger.uncertain_reserved_usd==Decimal('0.00065')
    with pytest.raises(SpendHold,match='LEDGER_FROZEN'):act()
    assert len(client.calls)==1
    assert 'abcdef' not in json.dumps(ledger.public_status())


def test_missing_usage_holds_future_calls():
    ledger,client,act=call(client=FakeClient(usage=False))
    with pytest.raises(SpendHold,match='USAGE_UNAVAILABLE_NO_FURTHER_CALLS'):act()
    assert ledger.frozen and ledger.calls_submitted==1
    assert ledger.uncertain_reserved_usd>0


def test_usage_above_reserved_input_fails():
    ledger,client,act=call(client=FakeClient(actual_input=1600))
    with pytest.raises(SpendHold,match='USAGE_EXCEEDS_PRE_SEND_RESERVATION'):act()
    assert ledger.frozen


def test_usage_above_reserved_output_fails():
    ledger,client,act=call(client=FakeClient(actual_output=1001))
    with pytest.raises(SpendHold,match='USAGE_EXCEEDS_PRE_SEND_RESERVATION'):act()
    assert ledger.frozen


def test_price_and_limits_invalid_fail():
    with pytest.raises(SpendHold,match='PRICE_INVALID'):
        SpendLedger('offline_mock',FrozenPrice('gpt-6-luna',Decimal('0'),Decimal('.5')),
                    default_offline_ledger().limits,OfflineTestCounter())
    with pytest.raises(SpendHold,match='LIMITS_INVALID'):
        SpendLedger('offline_mock',default_offline_ledger().price,
                    Limits(10,0,1000,8,Decimal('.5')),OfflineTestCounter())


def test_no_original_source_files_is_a_hold(tmp_path):
    state=inspect_local_sources(tmp_path)
    assert state['status']=='LOCAL_SOURCE_HOLD'
    with pytest.raises(SourceHold):require_official_local_sources(tmp_path)


def test_synthetic_files_pass_synthetic_manifest_but_never_official(tmp_path):
    synthetic={}
    for path in SOURCES:
        name=tmp_path/path
        name.parent.mkdir(parents=True,exist_ok=True)
        raw=(f'SYNTHETIC TEST FILE {path}').encode('utf-8')
        name.write_bytes(raw)
        synthetic[path]=git_blob_sha(raw)
    assert read_pinned_sources(tmp_path,synthetic).verified
    assert inspect_local_sources(tmp_path)['status']=='LOCAL_SOURCE_HOLD'


def test_tampered_and_symlink_files_refused(tmp_path):
    synthetic={}
    for path in SOURCES:
        f=tmp_path/path
        f.parent.mkdir(parents=True,exist_ok=True)
        data=b'fixture'+path.encode()
        f.write_bytes(data)
        synthetic[path]=git_blob_sha(data)
    f=tmp_path/next(iter(SOURCES))
    f.write_text('tampered')
    with pytest.raises(SourceHold,match='git_blob_mismatch'):read_pinned_sources(tmp_path,synthetic)
    f.unlink()
    # Explicit symlink leaf check
    valid=(tmp_path/list(SOURCES)[1]).resolve()
    f.symlink_to(valid)
    with pytest.raises(SourceHold,match='source_symlink_refused'):read_pinned_sources(tmp_path,synthetic)


def test_real_pair_refuses_source_hold_before_constructing_any_client(tmp_path):
    times=[]
    def factory():
        times.append(1)
        return FakeClient()
    settings=TransportSettings(model='gpt-6-luna',mode='offline_mock')
    with pytest.raises(SourceHold):
        run_checked_pair(source_root=tmp_path,client_factory=None,settings=settings,
                         ledger=default_offline_ledger(),private_dir=tmp_path/'private')
    assert times==[]
    assert not (tmp_path/'private').exists()


def test_live_pair_consent_refused_even_when_env_misleading(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','fake-nonsecret-not-real')
    monkeypatch.setenv('MINIFISH_G3_REAL_API_CONSENT','no')
    mock=default_offline_ledger()
    live=SpendLedger('live',mock.price,mock.limits,OfflineTestCounter())
    with pytest.raises(ExecutionHold,match='live_requires_separate_owner_consent'):
        run_checked_pair(source_root=tmp_path,client_factory=FakeClient,
                         settings=TransportSettings('gpt-6-luna',mode='live',allow_billable=True),
                         ledger=live,private_dir=tmp_path/'private')


def test_public_report_no_transcripts_or_private_token():
    ledger=default_offline_ledger()
    c=FakeClient()
    GuardedClient(c,ledger).create(**REQ)
    s=json.dumps(ledger.public_status())
    assert 'private question' not in s
    assert 'PRIVATE_TOKEN' not in s
    assert 'max_estimated_usd' not in s  # cap is explicitly labelled as a *modelled* limit


def test_request_hash_stable_under_key_reorder():
    assert payload_digest(REQ)==payload_digest(dict(reversed(list(REQ.items()))))


def test_official_counter_requires_separate_consent():
    from bonsai_g3_m1_guard import OfficialResponsesInputCounter
    with pytest.raises(SpendHold,match='OFFICIAL_COUNT_API_REQUIRES_SEPARATE_AUTHORIZATION'):
        OfficialResponsesInputCounter(SimpleNamespace(),authorized=False)


def test_official_counter_stub_counts_identical_model_and_history():
    from bonsai_g3_m1_guard import OfficialResponsesInputCounter
    calls=[]
    def count(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(input_tokens=1617)
    fake=SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=count)))
    receipt=OfficialResponsesInputCounter(fake,authorized=True).count(REQ)
    assert calls==[{'model':'gpt-6-luna','input':REQ['input']}]
    assert receipt.request_sha256==payload_digest(REQ)
    assert receipt.input_tokens==1617
    assert receipt.method=='official_responses_input_tokens'


def test_official_counter_fake_record_rejected_in_mock():
    from bonsai_g3_m1_guard import OfficialResponsesInputCounter
    fake=SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=lambda **_:SimpleNamespace(input_tokens=1400))))
    ledger=default_offline_ledger(counter=OfficialResponsesInputCounter(fake,authorized=True))
    c=FakeClient()
    with pytest.raises(SpendHold,match='MOCK_COUNTER_METHOD_REQUIRED'):
        GuardedClient(c,ledger).create(**REQ)
    assert not c.calls


def test_offline_runner_rejects_supplied_external_client_even_if_local_sources_missing(tmp_path):
    settings=TransportSettings(model='gpt-6-luna',mode='offline_mock')
    with pytest.raises(SpendHold,match='OFFLINE_EXTERNAL_CLIENT_FACTORY_FORBIDDEN'):
        run_checked_pair(source_root=tmp_path,client_factory=FakeClient,
                         settings=settings,ledger=default_offline_ledger(),
                         private_dir=tmp_path/'private')
    assert not (tmp_path/'private').exists()


def test_offline_multiturn_fixture_never_uses_network_and_generates_three_local_turns():
    from bonsai_g3_m1_guard import OfflineMultiTurnClient
    c=OfflineMultiTurnClient()
    first=c.responses.create(**REQ)
    assert first.output_text=='🎭 BONSaY 現行候補 v0.1d｜READY'
    for i in range(1,4):
        r=c.responses.create(**REQ)
        assert '模擬' in r.output_text
        assert f'C-IDEA{i}' in r.output_text
    assert len(c.calls)==4


def test_mock_pair_with_injected_synthetic_bundle_keeps_8_shared_budget_calls(tmp_path,monkeypatch):
    """Only a simulated bundle, not six real originals; test wiring of A+B."""
    from bonsai_g3_transport import SourceBundle
    import bonsai_g3_m1_guard as m1
    fake=SourceBundle(texts={p:'NOT AN ORIGINAL SOURCE' for p in SOURCES},
                      manifest=dict(SOURCES),verified=True)
    monkeypatch.setattr(m1,'require_official_local_sources',lambda root: fake)
    ledger=default_offline_ledger()
    result=run_checked_pair(source_root=tmp_path,client_factory=None,
                            settings=TransportSettings('gpt-6-luna',mode='offline_mock'),
                            ledger=ledger,private_dir=tmp_path/'PRIVATE')
    assert result['M1_shared_budget']['submitted_calls']==8
    assert result['A']['completed_generations']==3
    assert result['B']['completed_generations']==3
    assert result['M1_shared_budget']['frozen'] is False
    assert len(list((tmp_path/'PRIVATE').rglob('*_PRIVATE_transcript.json')))==2
    assert 'history' not in json.dumps(result)


def test_mock_pair_with_budget_too_small_refuses_before_first_model_request(tmp_path,monkeypatch):
    from bonsai_g3_transport import SourceBundle
    import bonsai_g3_m1_guard as m1
    fake=SourceBundle(texts={p:'NOT AN ORIGINAL SOURCE' for p in SOURCES},
                      manifest=dict(SOURCES),verified=True)
    monkeypatch.setattr(m1,'require_official_local_sources',lambda root: fake)
    base=default_offline_ledger()
    ledger=SpendLedger('offline_mock',base.price,
                       Limits(50000,400000,3000,8,Decimal('0.0001')),
                       OfflineTestCounter())
    result=run_checked_pair(source_root=tmp_path,client_factory=None,
                            settings=TransportSettings('gpt-6-luna',mode='offline_mock'),
                            ledger=ledger,private_dir=tmp_path/'PRIVATE')
    assert result['M1_shared_budget']['submitted_calls']==0
    assert ledger.frozen
    assert result['A']['status']=='HOLD'
    assert result['B']['status']=='HOLD'
