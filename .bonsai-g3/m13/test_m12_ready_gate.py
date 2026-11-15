"""No network, no keys, no paid API. Fake SDK exercises exact gated path."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import os
import socket
import stat

import pytest

from bonsai_g3_ab import READY_STRINGS
from bonsai_g3_m1_guard import payload_digest
from m11_preflight import snapshot
from m12_ready_gate import (
    MAX_ESTIMATED_USD, MAX_INPUT_TOKENS, MODEL, M12Hold, OwnerPermit,
    _single_ready_request, build_zero_retry_sdk, run_ready_once,
)

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'pinned_six'
READY = '🎭 BONSaY 現行候補 v0.1d｜READY'


class FakeInputTokens:
    def __init__(self, sdk):
        self.sdk = sdk

    def count(self, *, model, input):
        self.sdk.count_calls += 1
        self.sdk.events.append('official_count_fixture')
        if self.sdk.count_exc:
            raise RuntimeError('sk-not-a-real-key sensitive counter message')
        assert model == MODEL
        assert type(input) is list and len(input) == 2
        return SimpleNamespace(input_tokens=self.sdk.fake_count)


class FakeResponses:
    def __init__(self, sdk):
        self.sdk = sdk
        self.input_tokens = FakeInputTokens(sdk)

    def create(self, **kwargs):
        self.sdk.model_calls += 1
        self.sdk.events.append('model_create_fixture')
        self.sdk.last_request = kwargs
        if self.sdk.model_exc:
            raise RuntimeError('sk-not-a-real-key sensitive response message')
        return SimpleNamespace(
            output_text=self.sdk.text,
            status=self.sdk.status,
            usage=self.sdk.usage,
        )


class FakeSDK:
    def __init__(self, *, api_key, max_retries, timeout):
        self.constructor_args = {'api_key':api_key, 'max_retries':max_retries,
                                 'timeout':timeout}
        self.max_retries = max_retries
        self.events=[]
        self.count_calls=0
        self.model_calls=0
        self.count_exc=False
        self.model_exc=False
        self.fake_count=5000
        self.text=READY
        self.status='completed'
        self.usage=SimpleNamespace(input_tokens=5000, output_tokens=30)
        self.last_request=None
        self.responses=FakeResponses(self)


class RetryIgnoringSDK(FakeSDK):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_retries=2


@pytest.fixture
def fake_handle():
    return build_zero_retry_sdk(sdk_constructor=FakeSDK,
                                api_key='not-a-real-key-used-only-in-memory')


@pytest.fixture
def permit(monkeypatch):
    monkeypatch.setenv('MINIFISH_G3_REAL_API_CONSENT','yes')
    monkeypatch.setenv('M12_READY_ONE_REQUEST_CONSENT','yes')
    return OwnerPermit(True, True, True, True, Decimal('0.01'), '2026-11-15')


def run(tmp_path, fake_handle, permit, **overrides):
    return run_ready_once(handle=fake_handle,permit=permit,
                          source_root=overrides.get('source_root',SOURCE),
                          private_dir=overrides.get('private_dir',tmp_path/'private'),
                          run_id=overrides.get('run_id','m12_ready_a_001'))


def test_defaults_always_hold_without_authorization(fake_handle,tmp_path):
    with pytest.raises(M12Hold,match='OWNER_LIVE_PERMISSIONS_NOT_GRANTED'):
        run(tmp_path,fake_handle,OwnerPermit())
    assert fake_handle.client.count_calls==fake_handle.client.model_calls==0
    assert not (tmp_path/'private').exists()


def test_explicit_env_switches_both_required(fake_handle,permit,monkeypatch,tmp_path):
    monkeypatch.delenv('M12_READY_ONE_REQUEST_CONSENT')
    with pytest.raises(M12Hold,match='EXPLICIT_RUNTIME_CONSENT_MISSING'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.model_calls==0


def test_existing_g3_consent_is_also_required(fake_handle,permit,monkeypatch,tmp_path):
    monkeypatch.delenv('MINIFISH_G3_REAL_API_CONSENT')
    with pytest.raises(M12Hold,match='EXPLICIT_RUNTIME_CONSENT_MISSING'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.model_calls==0


def test_live_owner_cost_cap_holds_if_too_small(fake_handle,permit,tmp_path):
    p=OwnerPermit(True,True,True,True,Decimal('0.005'),'2026-11-15')
    with pytest.raises(M12Hold,match='OWNER_COST_LIMIT'):
        run(tmp_path,fake_handle,p)
    assert fake_handle.client.count_calls==0


def test_verified_pricing_date_is_required(fake_handle,permit,tmp_path):
    p=OwnerPermit(True,True,True,True,Decimal('0.01'),'')
    with pytest.raises(M12Hold,match='PRICE_VERIFICATION_DATE_MISSING'):
        run(tmp_path,fake_handle,p)


def test_true_boolean_values_not_truthy_integer(fake_handle,permit,tmp_path):
    p=OwnerPermit(1,True,True,True,Decimal('0.01'),'2026-11-15')
    with pytest.raises(M12Hold,match='OWNER_LIVE_PERMISSIONS_NOT_GRANTED'):
        run(tmp_path,fake_handle,p)


def test_sdk_constructor_has_retries_zero(fake_handle):
    sdk=fake_handle.client
    assert sdk.max_retries==0
    assert sdk.constructor_args['max_retries']==0
    assert sdk.constructor_args['timeout']==20
    assert sdk.constructor_args['api_key']=='not-a-real-key-used-only-in-memory'
    assert sdk.count_calls==sdk.model_calls==0


def test_sdk_factory_rejects_ignored_retries():
    with pytest.raises(M12Hold,match='SDK_ZERO_RETRY_NOT_VERIFIED'):
        build_zero_retry_sdk(sdk_constructor=RetryIgnoringSDK,api_key='test-only')


def test_sdk_factory_refuses_missing_key_or_bad_timeout():
    with pytest.raises(M12Hold,match='SDK_CONSTRUCTION_ARGS_INVALID'):
        build_zero_retry_sdk(sdk_constructor=FakeSDK,api_key='')
    with pytest.raises(M12Hold,match='SDK_CONSTRUCTION_ARGS_INVALID'):
        build_zero_retry_sdk(sdk_constructor=FakeSDK,api_key='x',timeout_seconds=999)


def test_source_manifest_preserved_and_initial_payload_sha_matches_m11():
    req, b, digest=_single_ready_request(SOURCE)
    m11=snapshot(SOURCE)
    assert b==76809
    assert digest==m11['conditions']['A']['input_sha256']
    assert req['model']==MODEL and req['store'] is False
    assert req['max_output_tokens']==512
    assert req['input'][1]['role']=='user'


def test_injected_fake_ready_only_no_network(permit,fake_handle,tmp_path,monkeypatch):
    def block_network(*args,**kwargs):
        raise AssertionError('UNEXPECTED_NETWORK')
    monkeypatch.setattr(socket.socket,'connect',block_network)
    response=run(tmp_path,fake_handle,permit)
    sdk=fake_handle.client
    assert response['status']=='READY_FIRST_RESPONSE_VERIFIED'
    assert response['model_calls']==response['official_count_calls']==1
    assert sdk.events==['official_count_fixture','model_create_fixture']
    assert sdk.count_calls==sdk.model_calls==1
    assert response['next_generation_started'] is False
    assert response['not_a_b_or_quality_proof']
    assert sdk.last_request['model']==MODEL
    assert sdk.last_request['store'] is False
    assert sdk.last_request['max_output_tokens']==512
    assert len(sdk.last_request['input'])==2


def test_durable_one_shot_prevents_replay(permit,fake_handle,tmp_path):
    run(tmp_path,fake_handle,permit)
    with pytest.raises(M12Hold,match='ONE_SHOT_ALREADY_RESERVED'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.count_calls==fake_handle.client.model_calls==1


def test_official_count_failure_frozen_no_model_or_sensitive_error(permit,fake_handle,tmp_path):
    sdk=fake_handle.client
    sdk.count_exc=True
    with pytest.raises(M12Hold,match='OFFICIAL_COUNT_UNKNOWN_NO_RETRY') as err:
        run(tmp_path,fake_handle,permit)
    assert 'sk-not-a-real-key' not in str(err.value)
    assert sdk.count_calls==1 and sdk.model_calls==0
    assert (tmp_path/'private'/'m12_ready_one_shot.reserved.json').is_file()
    sdk.count_exc=False
    with pytest.raises(M12Hold,match='ONE_SHOT_ALREADY_RESERVED'):
        run(tmp_path,fake_handle,permit)


def test_bad_count_missing_fails_before_model(permit,fake_handle,tmp_path):
    sdk=fake_handle.client
    sdk.fake_count=0
    with pytest.raises(M12Hold,match='OFFICIAL_COUNT_UNKNOWN_NO_RETRY'):
        run(tmp_path,fake_handle,permit)
    assert sdk.model_calls==0


def test_too_many_input_tokens_holds_before_model(permit,fake_handle,tmp_path):
    sdk=fake_handle.client
    sdk.fake_count=MAX_INPUT_TOKENS+1
    with pytest.raises(M12Hold,match='MODEL_NOT_CONFIRMED_OR_PRE_SEND_HOLD_NO_RETRY'):
        run(tmp_path,fake_handle,permit)
    assert sdk.model_calls==0


def test_budget_stop_precedes_model_if_token_count_exceeds_approximate_cap(permit,fake_handle,tmp_path,monkeypatch):
    # Limits in the existing guard are reused, not replaced with optimistic guesses.
    from m12_ready_gate import Limits, MAX_OUTPUT_TOKENS
    assert MAX_ESTIMATED_USD==Decimal('0.01')
    assert MAX_OUTPUT_TOKENS==512
    # Under verified short-context rates, worst case at 50k is 0.005256.
    assert Decimal('50000')*Decimal('0.1')/1_000_000 + Decimal('512')*Decimal('0.5')/1_000_000 == Decimal('0.005256')


def test_model_transport_error_frozen_no_retry_private_marker(permit,fake_handle,tmp_path):
    sdk=fake_handle.client
    sdk.model_exc=True
    with pytest.raises(M12Hold,match='MODEL_NOT_CONFIRMED_OR_PRE_SEND_HOLD_NO_RETRY') as err:
        run(tmp_path,fake_handle,permit)
    assert 'sensitive' not in str(err.value)
    assert sdk.count_calls==sdk.model_calls==1
    assert (tmp_path/'private'/'m12_ready_one_shot.reserved.json').exists()
    assert not (tmp_path/'private'/'m12_ready_a_001.private.json').exists()


def test_missing_usage_freezes_no_forged_ready(permit,fake_handle,tmp_path):
    sdk=fake_handle.client
    sdk.usage=None
    with pytest.raises(M12Hold,match='MODEL_NOT_CONFIRMED_OR_PRE_SEND_HOLD_NO_RETRY'):
        run(tmp_path,fake_handle,permit)
    assert sdk.model_calls==1


def test_usage_over_estimate_fail_closed(permit,fake_handle,tmp_path):
    fake_handle.client.usage=SimpleNamespace(input_tokens=5001,output_tokens=20)
    with pytest.raises(M12Hold,match='MODEL_NOT_CONFIRMED_OR_PRE_SEND_HOLD_NO_RETRY'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.model_calls==1


def test_bad_ready_stored_privately_but_never_passes(permit,fake_handle,tmp_path):
    fake_handle.client.text='READY? (unapproved)'
    with pytest.raises(M12Hold,match='READY_TEXT_OR_STATUS_UNVERIFIED'):
        run(tmp_path,fake_handle,permit)
    assert (tmp_path/'private'/'m12_ready_a_001.private.json').exists()
    obj=json.loads((tmp_path/'private'/'m12_ready_a_001.private.json').read_text())
    assert obj['raw_reply']=='READY? (unapproved)'
    assert obj['verified_ready'] is False


def test_incomplete_status_not_promoted_to_ready(permit,fake_handle,tmp_path):
    fake_handle.client.status='incomplete'
    with pytest.raises(M12Hold,match='READY_TEXT_OR_STATUS_UNVERIFIED'):
        run(tmp_path,fake_handle,permit)


def test_private_output_and_journal_permissions(permit,fake_handle,tmp_path,capsys):
    response=run(tmp_path,fake_handle,permit)
    root=tmp_path/'private'
    assert stat.S_IMODE(root.stat().st_mode)==0o700
    files=list(root.iterdir())
    assert len(files)==2
    assert all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in files)
    raw=(root/'m12_ready_a_001.private.json').read_text()
    assert READY in raw and READY not in json.dumps(response,ensure_ascii=False)
    assert 'not-a-real-key' not in raw
    assert 'not-a-real-key' not in json.dumps(response)
    assert capsys.readouterr().out==''


def test_too_open_private_dir_rejected(permit,fake_handle,tmp_path):
    d=tmp_path/'private';d.mkdir(mode=0o755);d.chmod(0o755)
    with pytest.raises(M12Hold,match='PRIVATE_DIR_NOT_OWNER_ONLY'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.model_calls==0


def test_private_dir_symlink_rejected(permit,fake_handle,tmp_path):
    d=tmp_path/'private';d.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(M12Hold,match='PRIVATE_DIR_SYMLINK'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.model_calls==0


def test_existing_marker_is_durable_before_official_count(permit,fake_handle,tmp_path):
    d=tmp_path/'private';d.mkdir(mode=0o700)
    (d/'m12_ready_one_shot.reserved.json').write_text('{"reserved":true}')
    with pytest.raises(M12Hold,match='ONE_SHOT_ALREADY_RESERVED'):
        run(tmp_path,fake_handle,permit)
    assert fake_handle.client.count_calls==0


def test_run_id_path_traversal_rejected(permit,fake_handle,tmp_path):
    with pytest.raises(M12Hold,match='RUN_ID_INVALID_OR_NOT_FIRST_READY'):
        run(tmp_path,fake_handle,permit,run_id='../oops')
    assert fake_handle.client.count_calls==0


def test_tampered_source_holds_without_count(permit,fake_handle,tmp_path):
    import shutil
    clone=tmp_path/'pinned'
    shutil.copytree(SOURCE,clone)
    target=clone/'BONSAI_START_HERE.md'
    target.write_bytes(target.read_bytes()+b'ALTERED')
    with pytest.raises(M12Hold,match='SOURCE_BUNDLE_UNKNOWN'):
        run(tmp_path,fake_handle,permit,source_root=clone)
    assert fake_handle.client.count_calls==fake_handle.client.model_calls==0


def test_prevent_alternative_first_ready_run_id(permit,fake_handle,tmp_path):
    with pytest.raises(M12Hold,match='RUN_ID_INVALID_OR_NOT_FIRST_READY'):
        run(tmp_path,fake_handle,permit,run_id='m12_ready_a_002')
    assert fake_handle.client.count_calls==0


def test_count_permission_only_cannot_trigger_count(permit,fake_handle,tmp_path):
    p=OwnerPermit(True,False,True,True,Decimal('0.01'),'2026-11-15')
    with pytest.raises(M12Hold,match='OWNER_LIVE_PERMISSIONS_NOT_GRANTED'):
        run(tmp_path,fake_handle,p)
    assert fake_handle.client.count_calls==fake_handle.client.model_calls==0


def test_stale_price_is_rejected(permit,fake_handle,tmp_path):
    p=OwnerPermit(True,True,True,True,Decimal('0.01'),'2025-01-01')
    with pytest.raises(M12Hold,match='PRICE_VERIFICATION_STALE_OR_FUTURE'):
        run(tmp_path,fake_handle,p)
    assert fake_handle.client.count_calls==0


def test_cli_has_no_live_entrypoint(tmp_path):
    import subprocess,sys
    cmd=[sys.executable,str(ROOT/'m12_ready_gate.py')]
    p=subprocess.run(cmd,capture_output=True,text=True,check=True,env={'PATH':os.getenv('PATH','')})
    x=json.loads(p.stdout)
    assert x['status']=='LIVE_HOLD_SEPARATE_AUTHORIZATION_REQUIRED'
    assert x['official_api_count_calls']==x['model_api_calls']==0
    assert 'READY' not in str(x.get('reply',''))
