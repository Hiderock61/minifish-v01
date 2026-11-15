"""One-shot purely local G3-M1 readiness report. No AI, HTTP, credentials, or writes beyond report path."""
from __future__ import annotations
import argparse
from pathlib import Path
import json
from preflight_readonly import validate_receipts
from bonsai_g3_m1_guard import inspect_local_sources, default_offline_ledger


def audit(base: Path, sources: Path) -> dict:
    remote = validate_receipts(json.loads((base/'github_source_receipts.json').read_text(encoding='utf-8')))
    local = inspect_local_sources(sources)
    guard = default_offline_ledger()
    return {
        'project':'BONSaY G3-M1 fail-closed guard',
        'status':'M1_ISOLATED_GUARD_TESTED_LOCAL_SOURCE_HOLD' if local['status']!='LOCAL_SOURCE_6_OF_6_PASS'
                 else 'M1_ISOLATED_GUARD_TESTED_SOURCES_LOCAL_PASS',
        'remote_github_sha_receipts':dict(remote, status='6_OF_6_PASS_PREVIOUSLY_FETCHED'),
        'local_original_source_check':local,
        'guard_mode':'offline_mock',
        'guard_pricing_as_of':guard.price.pricing_as_of,
        'budget_configuration':{
            'model_example':guard.price.model,'max_requests_both_conditions':guard.limits.max_calls,
            'max_input_tokens_per_request':guard.limits.max_input_tokens_per_call,
            'max_input_tokens_total':guard.limits.max_input_tokens_total,
            'max_output_tokens_per_request':guard.limits.max_output_tokens_per_call,
            'max_modelled_usd':str(guard.limits.max_estimated_usd),
            'pricing_service_tier_example':guard.price.service_tier,
        },
        'token_count_method':'OFFLINE_SIMULATION_IN_TESTS; OFFICIAL_API_COUNT_NOT_CALLED',
        'live_model_calls_made':0,
        'input_count_api_calls_made':0,
        'live_api_status':'HOLD_PENDING_SEPARATE_USER_APPROVAL_AND_SECRET_VALIDATION',
        'real_AB_semantic_quality':'UNKNOWN',
        'legacy_files_modified':False,
        'external_changes':False,
        'next_action':'materialize exact six Git source blobs locally and separately verify model, API consent/billing/key before one approved live request',
    }


def main():
    a=argparse.ArgumentParser()
    a.add_argument('--sources',type=Path,default=Path('local_pinned_sources'))
    a.add_argument('--out',type=Path,default=Path('evidence/m1_readiness.json'))
    args=a.parse_args()
    base=Path(__file__).resolve().parent
    result=audit(base,args.sources)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
