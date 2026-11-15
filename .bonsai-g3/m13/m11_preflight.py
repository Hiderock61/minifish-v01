"""BONSaY G3-M11: no-key, no-network, no-payment pre-live audit.

This executable intentionally does not import the OpenAI SDK or invoke an API.
It verifies existing pinned source bytes and produces conservative, evidence-aware
readiness statements. The only output is a sanitized JSON receipt.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
import json

from bonsai_g3_ab import SOURCES, START_PROMPT, B_ADDENDUM, T0
from bonsai_g3_transport import _instructions
from bonsai_g3_m1_guard import default_offline_ledger, require_official_local_sources

SOURCE_PATHS = [
    'BONSAI_START_HERE.md',
    'methods/006_hiderock-gekidan-method.md',
    'methods/006A_hiderock-gekidan-roster.md',
    'methods/006B_hiderock-gekidan-emoji-legend.md',
    'methods/006C_hideroko-injection-protocol.md',
    'experiments/bonsai-performance-runtime-v0.1d-candidate.md',
]


def cost_usd(input_tokens: int, output_tokens: int, input_rate: Decimal, output_rate: Decimal) -> Decimal:
    for number in (input_tokens, output_tokens):
        if type(number) is not int or number < 0:
            raise ValueError('TOKENS_NOT_VALIDATED')
    return (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(1_000_000)


def snapshot(root: Path) -> dict[str, Any]:
    bundle = require_official_local_sources(root)
    if list(SOURCES) != SOURCE_PATHS:
        raise ValueError('FROZEN_SIX_DOCUMENT_ORDER_CHANGED')
    dev = _instructions(bundle)
    ledger = default_offline_ledger()
    budget = ledger.limits
    if ledger.price.model != 'gpt-6-luna':
        raise ValueError('MODEL_FROM_FROZEN_CONTRACT_CHANGED')

    # First request is prepared byte-for-byte as in run_session, but not submitted.
    request_details: dict[str, Any] = {}
    for cond in ('A', 'B'):
        first = START_PROMPT + (B_ADDENDUM if cond == 'B' else '')
        payload = [ {'role':'developer','content':dev}, {'role':'user','content':first} ]
        raw = json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        request_details[cond] = {
            'input_sha256': sha256(raw).hexdigest(),
            'input_utf8_bytes': len(raw),
            'official_input_tokens': None,
            'first_input_below_900000_bytes': len(raw) <= 900_000,
            'api_requests': 0,
        }

    unit_price_in = ledger.price.input_usd_per_million
    unit_price_out = ledger.price.output_usd_per_million
    worst = cost_usd(budget.max_input_tokens_total,budget.max_output_tokens_per_call*budget.max_calls,unit_price_in,unit_price_out)
    cost_for_full_output = cost_usd(0,budget.max_output_tokens_per_call*budget.max_calls,unit_price_in,unit_price_out)
    max_input_tokens_for_fixed_output_cap = int((budget.max_estimated_usd-cost_for_full_output) / unit_price_in * Decimal(1_000_000))
    # Independent quality audit, no actual outputs today.
    return {
        'experiment': 'BONSaY G3 T0航路チェック A/B pilot',
        'phase': 'G3-M11_PRELIVE_READ_ONLY',
        'model': ledger.price.model,
        'source_bytes_verified': sum(len(t.encode('utf8')) for t in bundle.texts.values()),
        'source_count_verified': len(bundle.texts),
        'six_git_blob_sha_matched': True,
        'T0': T0,
        'user_messages_per_condition': ['READY_PROMPT','FIXED_T0','あ','あ'],
        'conditions': request_details,
        'max_calls_total': budget.max_calls,
        'max_output_tokens_per_call': budget.max_output_tokens_per_call,
        'input_tokens_total_cap':budget.max_input_tokens_total,
        'input_tokens_per_call_cap': budget.max_input_tokens_per_call,
        'local_estimated_spend_cap_usd': str(budget.max_estimated_usd),
        'standard_short_context_rates_usd_per_million':{'input':str(unit_price_in),'output':str(unit_price_out)},
        'cost_worst_case_usd':str(worst),
        'max_input_tokens_total_for_worst_case_within_current_cap':max_input_tokens_for_fixed_output_cap,
        'full_8_call_completion_guaranteed_by_local_cap':worst <= budget.max_estimated_usd,
        'can_claim_correct_api_price_now': 'CONDITIONAL_ON_MODEL_PROCESSING_MODE_AND_UP_TO_DATE_RATES',
        'can_claim_monthly_hard_spend_limit':False,
        'sdk_runtime_at_pr47_for_minifish_tests':'OBSERVED_PYTHON311_BUT_NOT_G3_LIVE_CLIENT',
        'sdk_client_retry_zero_verified':'UNKNOWN_NO_LIVE_CLIENT_CONFIG',
        'fixed_model_project_access':'UNKNOWN_NOT_AUTHENTICATED',
        'api_key_presence_and_validity':'UNKNOWN_NOT_CHECKED',
        'official_input_token_count':'UNKNOWN_NOT_CALLED',
        'billing_available':'UNKNOWN_NOT_CHECKED',
        'external_token_count_authorization':'NOT_GRANTED',
        'model_api_authorization':'NOT_GRANTED',
        'reasoning_effort_fixed':'UNKNOWN_DEFAULT_ONLY',
        'start_prompt_external_url_read_assurance':'NOT_VERIFIED_URL_IS_ONLY_A_REFERENCE',
        'a_b_semantic_quality':'UNKNOWN_NOT_MEASURED',
        'pilot_generalizability':'UNSUPPORTED_SINGLE_T0_SINGLE_PAIR',
        'api_requests_executed':0,
        'official_token_counter_calls_executed':0,
        'authenticated_reads_executed':0,
        'github_writes_executed':0,
        'readiness':'LIVE_HOLD',
        'independent_holds':[
            'KEY_PROJECT_MODEL_ACCESS_UNKNOWN',
            'OFFICIAL_INPUT_TOKEN_COUNT_UNKNOWN',
            'OWNER_LIVE_REQUEST_AND_BILLABLE_CONSENT_NOT_GRANTED',
            'SDK_RETRIES_MUST_BE_FORCED_TO_ZERO',
            'BUDGET_8_CALL_MAX_NOT_GUARANTEED',
            'A_B_SUCCESS_RUBRIC_NOT_YET_SCORED',
        ],
    }


def main() -> None:
    root = Path(__file__).resolve().parent / 'pinned_six'
    receipt = snapshot(root)
    target = Path(__file__).resolve().parent / 'm11_readonly_receipt.json'
    target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:receipt[k] for k in (
        'phase','readiness','source_count_verified','source_bytes_verified',
        'cost_worst_case_usd','full_8_call_completion_guaranteed_by_local_cap',
        'api_requests_executed','github_writes_executed')},ensure_ascii=False,indent=2))

if __name__ == '__main__':main()
