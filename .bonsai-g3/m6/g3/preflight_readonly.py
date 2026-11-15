"""BONSaY P1 G3 preflight: read-only, no network, no API, no credentials.

The remotely inspected SHA receipts are independent from local source-materialization.
This script never claims token counts are accurate from byte counts.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'G3_Transport_v0.2'))
from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import DEFAULT_OUTPUT_TOKENS, MAX_REQUESTS_PER_CONDITION, \
    MAX_INPUT_BYTES, TransportSettings, ExecutionHold, SourceHold, read_pinned_sources

# USD pricing, OpenAI official standard text rate, 2026-11-15.
# gpt-6-luna; cached input discounts deliberately not counted.
PRICE = {'model':'gpt-6-luna','input_usd_per_million':0.10,'output_usd_per_million':0.50}


def validate_receipts(receipts: dict[str, Any]) -> dict[str, Any]:
    recs=receipts.get('sources', [])
    bypath={v.get('path'):v for v in recs}
    if len(recs)!=len(SOURCES) or set(bypath)!=set(SOURCES):
        raise SourceHold('REMOTE_RECEIPTS_PATH_MISMATCH')
    for path,expected in SOURCES.items():
        obj=bypath[path]
        if obj.get('sha')!=expected or obj.get('expected_sha')!=expected or obj.get('sha_matched') is not True:
            raise SourceHold('REMOTE_RECEIPT_MISMATCH_'+path)
        if not isinstance(obj.get('utf8_bytes'),int) or obj['utf8_bytes']<=0:
            raise SourceHold('REMOTE_RECEIPT_SIZE_INVALID_'+path)
    return {'count':len(recs),'sum_utf8_bytes':sum(by_path['utf8_bytes'] for by_path in recs),
            'all_sha_matched':True}


def modeled_cost(estimated_source_input_tokens_each_call: int,
                 * , prior_output_history_tokens_total: int = 36000,
                 output_tokens_total: int = 24000) -> dict:
    if not 0 < estimated_source_input_tokens_each_call <= 1_050_000:
        raise ValueError('invalid_assumption')
    # Order 2 independent conversations, READY, T0, あ, あ = 8 requests.
    # Max prior output history = 2 * (0+3000+6000+9000) = 36000 tokens.
    # These figures are *scenarios*, not a certifiable spend ceiling.
    req=2*MAX_REQUESTS_PER_CONDITION
    inp=req*estimated_source_input_tokens_each_call + prior_output_history_tokens_total
    out=output_tokens_total
    usd=inp*PRICE['input_usd_per_million']/1_000_000 + out*PRICE['output_usd_per_million']/1_000_000
    return {'assumed_base_input_tokens_per_request':estimated_source_input_tokens_each_call,
            'assumed_total_input_tokens':inp,'assumed_total_output_tokens':out,
            'usd_unbilled_scenario':round(usd,5)}


def audit(package_root: Path, local_source_root: Path|None = None) -> dict:
    p=Path(package_root)
    receipt=json.loads((p/'github_source_receipts.json').read_text(encoding='utf-8'))
    remote=validate_receipts(receipt)
    preexisting_tests={'passed':30,'provenance':'prior G3 test suite; rerun separately to confirm'}
    local='HOLD_LOCAL_FILES_NOT_PRESENT'
    if local_source_root is not None:
        try:
            b=read_pinned_sources(local_source_root)
            local='PASS_LOCAL_GIT_BLOBS_VERIFIED' if b.verified else 'HOLD_UNVERIFIED'
        except SourceHold as e:
            local='HOLD_'+str(e)
    # Always fail closed for live without separate owner consent. Do not inspect real API keys.
    live_blocked=False
    try:
        TransportSettings('gpt-6-luna', mode='live', allow_billable=False).check()
    except ExecutionHold:
        live_blocked=True
    if not live_blocked:
        raise RuntimeError('FAIL_LIVE_WAS_NOT_GATED')
    r={
      'report_kind':'READ_ONLY_OFFLINE_PREFLIGHT',
      'as_of':'2026-11-15',
      'repository':'Hiderock61/hiderock-method-os',
      'remote_source':dict(remote, status='REMOTE_SHA_6_OF_6_PASS'),
      'local_source_status':local,
      'total_source_bytes':remote['sum_utf8_bytes'],
      'planned_conditions':['A','B'],
      'calls_per_condition':MAX_REQUESTS_PER_CONDITION,
      'max_calls_total':2*MAX_REQUESTS_PER_CONDITION,
      'max_generation_output_tokens_per_call':DEFAULT_OUTPUT_TOKENS,
      'total_possible_generated_tokens_if_all_hit_request_ceiling':2*MAX_REQUESTS_PER_CONDITION*DEFAULT_OUTPUT_TOKENS,
      'min_source_body_bytes_sent_across_8_calls':remote['sum_utf8_bytes']*2*MAX_REQUESTS_PER_CONDITION,
      'note':'The minimum source-body bytes excludes wrappers, JSON escaping, user prompts and prior assistant replies. It is not total input bytes or token usage.',
      'api_input_tokens':'UNKNOWN_REQUIRES_MODEL_EXACT_INPUT_TOKENS_COUNT',
      'key_validity':'UNKNOWN_NOT_READ',
      'billing_balance':'UNKNOWN_NOT_READ',
      'project_hard_spend_limit':'UNKNOWN_NOT_READ',
      'model_access':'UNKNOWN_NOT_TESTED',
      'unit_prices':PRICE,
      'usd_cost_scenarios':[modeled_cost(n) for n in (20000,32000,45000)],
      'cost_scenarios_are_not_hard_caps':True,
      'live_with_no_explicit_consent_blocked':live_blocked,
      'required_before_real_api_go':[
        'Verified local bytes for 6 sources (and no source symlinks)',
        'Fixed model ID, reasoning effort, output cap, region and service tier',
        'Exact token count for each request, cumulative input budget and pre-send ceiling',
        'Separate API billing approval and current organization/project spend cap',
        'Valid newly rotated key in an approved private execution environment',
        'No public transcripts, tokens or secret values in Github Issue or artifact',
        'Original G3 v0.2 freeze until modifications independently tested'
      ],
      'live_run_status':'HOLD',
      'semantic_quality_status':'UNKNOWN',
      'mutated_external_resources':False,
      'api_calls_made':0
    }
    return r

if __name__=='__main__':
    here=Path(__file__).resolve().parent
    report=audit(here)
    (here/'preflight_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('remote_source','local_source_status','max_calls_total','api_input_tokens','live_run_status','api_calls_made')},ensure_ascii=False,indent=2))
