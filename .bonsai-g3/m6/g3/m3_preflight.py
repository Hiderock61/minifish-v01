"""BONSaY G3-M3: read-only, zero network/API or credential access."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import importlib.metadata
import json
from bonsai_g3_ab import SOURCES, START_PROMPT, B_ADDENDUM
from bonsai_g3_transport import _instructions
from bonsai_g3_m1_guard import default_offline_ledger, require_official_local_sources


def sdk_metadata():
    # Never instantiate SDK client, inspect env keys, or access connected accounts.
    try:
        version = importlib.metadata.version('openai')
        from openai import OpenAI
        if not callable(OpenAI):
            return {'status':'SDK_NOT_AVAILABLE', 'version':version}
        return {'status':'SDK_INSTALLED_NOT_AUTHENTICATED', 'version':version}
    except (ImportError, AttributeError, importlib.metadata.PackageNotFoundError):
        return {'status':'SDK_NOT_AVAILABLE', 'version':None}


def cost_at_cap(input_tokens:int, output_tokens:int,
                inp:Decimal=Decimal('0.10'), out:Decimal=Decimal('0.50')) -> Decimal:
    if (type(input_tokens) is not int or type(output_tokens) is not int or
        input_tokens<0 or output_tokens<0):
        raise ValueError('invalid token input')
    return (Decimal(input_tokens)*inp + Decimal(output_tokens)*out)/Decimal(1000000)


def audit(root:Path):
    bundle = require_official_local_sources(root)
    developer = _instructions(bundle)
    ledger = default_offline_ledger()
    budget = ledger.limits
    byte_count = sum(len(bundle.texts[p].encode('utf-8')) for p in SOURCES)
    if byte_count != 76809:
        raise ValueError('unexpected six source byte size')
    first_input={}
    for label, value in (('A',START_PROMPT), ('B',START_PROMPT+B_ADDENDUM)):
        messages = [{'role':'developer','content':developer},{'role':'user','content':value}]
        b=json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        first_input[label]={
            'request_utf8_bytes':len(b), 'request_sha256':sha256(b).hexdigest(),
            'under_900000_byte_ceiling':len(b)<=900000,
            'input_tokens':'UNKNOWN_NO_OFFICIAL_COUNT',
        }
    one_cap = cost_at_cap(budget.max_input_tokens_per_call,budget.max_output_tokens_per_call)
    all_cap = cost_at_cap(budget.max_input_tokens_total,budget.max_calls*budget.max_output_tokens_per_call)
    return {
        'project':'BONSaY_G3_M3_READ_ONLY',
        'utc':datetime.now(timezone.utc).isoformat(),
        'local_source_status':'6_OF_6_PASS','local_source_bytes':byte_count,
        'sdk':sdk_metadata(),
        'model_documented':'gpt-6-luna', 'project_model_access':'UNKNOWN_NO_AUTHORIZED_PROBE',
        'official_input_tokens':'UNKNOWN_NOT_CALLED',
        'key_validity':'UNKNOWN_NOT_INSPECTED',
        'balance_or_credits':'UNKNOWN_NOT_INSPECTED',
        'project_billing_hard_limit':'UNKNOWN_NOT_INSPECTED',
        'owner_approval_for_paid_network_requests':False,
        'standard_price_per_million_usd':{'input':'0.10','output':'0.50'},
        'first_request':first_input,
        'budget':{
            'max_calls':budget.max_calls,
            'max_input_tokens_per_call':budget.max_input_tokens_per_call,
            'max_total_input_tokens':budget.max_input_tokens_total,
            'output_tokens_per_call':budget.max_output_tokens_per_call,
            'app_estimated_usd_cap':str(budget.max_estimated_usd),
            'max_one_request_estimated_usd':str(one_cap),
            'max_eight_requests_estimated_usd':str(all_cap),
            'max_eight_requests_within_app_cap':all_cap<=budget.max_estimated_usd,
        },
        'model_requests':0, 'official_count_requests':0,'credential_reads':0,
        'external_writes':0, 'live_readiness':'HOLD',
        'next':'Verify key, organization/project model entitlement, precise input tokens and explicit spend authorization in a separate approved operation',
    }

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    report = audit(root/'pinned_six')
    (root/'evidence').mkdir(exist_ok=True)
    (root/'evidence'/'m3_preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
