"""BONSaY G3 M12: first READY response only, with fail-closed live gates.

Default CLI is no-network and cannot send to a model. This library accepts an
*injected* SDK client only after separately authorized owner/project/price gates.
Tests exercise the exact count -> budget -> model path with local fake clients.
It never reads an API key, calls GitHub, or silently enables chargeable work.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import os
import re
import stat

from bonsai_g3_ab import START_PROMPT, SOURCES, READY_STRINGS
from bonsai_g3_transport import TransportSettings, _instructions
from bonsai_g3_m1_guard import (
    FrozenPrice, Limits, OfficialResponsesInputCounter, SpendLedger,
    SpendHold, TokenCountReceipt, payload_digest, require_official_local_sources,
)

MODEL = 'gpt-6-luna'
MAX_OUTPUT_TOKENS = 512                  # first READY only, smaller than M11's 3,000
MAX_INPUT_TOKENS = 50_000
MAX_ESTIMATED_USD = Decimal('0.01')     # local estimate, NOT an invoice/account hard cap
INPUT_USD_PER_MILLION = Decimal('0.10')
OUTPUT_USD_PER_MILLION = Decimal('0.50')
RUN_ID_PATTERN = re.compile(r'^m12_ready_[a-z0-9_-]{1,50}$')


class M12Hold(Exception):
    """Safe constant reason only; API exception text is never surfaced."""


@dataclass(frozen=True)
class OwnerPermit:
    """All false by default. A chat 'あ' or an existing key is not a live grant."""
    authorized_official_count: bool = False
    authorized_paid_ready: bool = False
    verified_project_key_and_model: bool = False
    verified_current_price_tier_and_balance: bool = False
    owner_cost_cap_usd: Decimal = Decimal('0')
    price_verified_date: str = ''

    def check(self) -> None:
        if any(type(x) is not bool or x is not True for x in (
                self.authorized_official_count,
                self.authorized_paid_ready,
                self.verified_project_key_and_model,
                self.verified_current_price_tier_and_balance)):
            raise M12Hold('OWNER_LIVE_PERMISSIONS_NOT_GRANTED')
        if (type(self.owner_cost_cap_usd) is not Decimal
                or not self.owner_cost_cap_usd.is_finite()
                or self.owner_cost_cap_usd < MAX_ESTIMATED_USD):
            raise M12Hold('OWNER_COST_LIMIT_TOO_SMALL_OR_UNKNOWN')
        try:
            verified = date.fromisoformat(self.price_verified_date)
        except (ValueError, TypeError):
            raise M12Hold('PRICE_VERIFICATION_DATE_MISSING') from None
        # A static rate is not perpetual: do not silently rely on old prices.
        if verified > date.today() or date.today() - verified > timedelta(days=7):
            raise M12Hold('PRICE_VERIFICATION_STALE_OR_FUTURE')
        if (os.getenv('MINIFISH_G3_REAL_API_CONSENT') != 'yes'
                or os.getenv('M12_READY_ONE_REQUEST_CONSENT') != 'yes'):
            raise M12Hold('EXPLICIT_RUNTIME_CONSENT_MISSING')


@dataclass(frozen=True)
class StrictSdkHandle:
    """Construct via build_zero_retry_sdk(), never assume injected client is safe."""
    client: Any


def build_zero_retry_sdk(*, sdk_constructor: Any, api_key: str,
                         timeout_seconds: float = 20.0) -> StrictSdkHandle:
    """SDK initialization only. No network or API counting occurs here.

    With real SDK, sdk_constructor is openai.OpenAI, supplied explicitly by a
    separately authorized caller. Do NOT read credentials from env by default.
    """
    if not isinstance(api_key, str) or not api_key or not 0 < timeout_seconds <= 30:
        raise M12Hold('SDK_CONSTRUCTION_ARGS_INVALID')
    try:
        client = sdk_constructor(api_key=api_key, max_retries=0,
                                 timeout=timeout_seconds)
    except Exception:
        raise M12Hold('SDK_CONSTRUCTION_UNKNOWN') from None
    if type(getattr(client, 'max_retries', None)) is not int or client.max_retries != 0:
        raise M12Hold('SDK_ZERO_RETRY_NOT_VERIFIED')
    if not callable(getattr(getattr(client, 'responses', None), 'create', None)):
        raise M12Hold('SDK_RESPONSE_CREATE_MISSING')
    if not callable(getattr(getattr(getattr(client, 'responses', None), 'input_tokens', None), 'count', None)):
        raise M12Hold('SDK_OFFICIAL_COUNT_MISSING')
    return StrictSdkHandle(client)


def _private_root(root: Path) -> Path:
    root = Path(root)
    if root.is_symlink():
        raise M12Hold('PRIVATE_DIR_SYMLINK')
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir() or (stat.S_IMODE(root.stat().st_mode) & 0o077):
            raise M12Hold('PRIVATE_DIR_NOT_OWNER_ONLY')
    except M12Hold:
        raise
    except OSError:
        raise M12Hold('PRIVATE_DIR_UNAVAILABLE') from None
    return root


def _private_write_new(path: Path, obj: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        raise M12Hold('ONE_SHOT_ALREADY_RESERVED') from None
    except OSError:
        # Partially written marker is intentionally left in place: fail closed.
        raise M12Hold('PRIVATE_WRITE_UNCERTAIN') from None


class _CachedOfficialCounter:
    """No second official count; ties exactly one counted payload to one send."""
    def __init__(self, receipt: TokenCountReceipt):
        self.receipt = receipt
        self.calls = 0

    def count(self, request: dict[str, Any]) -> TokenCountReceipt:
        self.calls += 1
        if self.calls != 1 or self.receipt.request_sha256 != payload_digest(request):
            raise SpendHold('OFFICIAL_COUNT_PAYLOAD_CHANGED')
        return self.receipt


def _single_ready_request(source_root: Path) -> tuple[dict[str, Any], int, str]:
    bundle = require_official_local_sources(source_root)
    if set(bundle.texts) != set(SOURCES):
        raise M12Hold('SIX_SOURCE_SET_INCOMPLETE')
    source_bytes = sum(len(t.encode('utf-8')) for t in bundle.texts.values())
    if source_bytes != 76_809:
        raise M12Hold('SOURCE_BYTES_DIFFER_FROM_M11')
    call_input = [
        {'role':'developer', 'content':_instructions(bundle)},
        {'role':'user', 'content':START_PROMPT},
    ]
    raw = json.dumps(call_input, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(raw) > 900_000:
        raise M12Hold('INPUT_BYTES_OVER_CAP')
    request = dict(model=MODEL, input=call_input, max_output_tokens=MAX_OUTPUT_TOKENS,
                   store=False)
    return request, source_bytes, sha256(raw).hexdigest()


def _strict_client(handle: StrictSdkHandle) -> Any:
    if type(handle) is not StrictSdkHandle or getattr(handle.client, 'max_retries', None) != 0:
        raise M12Hold('SDK_ZERO_RETRY_NOT_VERIFIED')
    return handle.client


def run_ready_once(*, handle: StrictSdkHandle, permit: OwnerPermit,
                   source_root: Path, private_dir: Path,
                   run_id: str = 'm12_ready_a_001') -> dict[str, Any]:
    """At most one count and one model create; no retry or second generation.

    There is deliberately no CLI invocation for this function. Future *explicit*
    external authorization, real SDK client setup, project/rate verification,
    and privacy review are prerequisites. Tests inject fake in-memory SDKs.
    """
    permit.check()                   # BEFORE disk, counter, or model activity
    if run_id != 'm12_ready_a_001' or not RUN_ID_PATTERN.fullmatch(run_id):
        raise M12Hold('RUN_ID_INVALID_OR_NOT_FIRST_READY')
    client = _strict_client(handle)
    TransportSettings(model=MODEL, mode='live', allow_billable=True,
                      output_tokens=MAX_OUTPUT_TOKENS).check()
    try:
        request, source_bytes, input_sha = _single_ready_request(source_root)
    except M12Hold:
        raise
    except Exception:
        raise M12Hold('SOURCE_BUNDLE_UNKNOWN') from None
    private_root = _private_root(private_dir)
    request_sha = payload_digest(request)
    # Stable singleton marker, independent of caller-provided names.
    marker = private_root / 'm12_ready_one_shot.reserved.json'
    receipt_path = private_root / (run_id + '.private.json')
    # This durable one-shot marker is created BEFORE the official count API;
    # connection losses, process crashes, and uncertain failures cannot replay.
    _private_write_new(marker, {
        'state':'ATTEMPT_RESERVED_NO_AUTOMATIC_RETRY',
        'run_id':run_id, 'request_sha256':request_sha,
        'input_sha256':input_sha, 'source_bytes':source_bytes,
        'max_model_calls':1, 'max_count_calls':1,
        'max_estimated_usd':str(MAX_ESTIMATED_USD),
    })
    try:
        official = OfficialResponsesInputCounter(client, authorized=True).count(request)
    except Exception:
        raise M12Hold('OFFICIAL_COUNT_UNKNOWN_NO_RETRY') from None
    counter = _CachedOfficialCounter(official)
    ledger = SpendLedger(
        mode='live',
        price=FrozenPrice(MODEL, INPUT_USD_PER_MILLION, OUTPUT_USD_PER_MILLION,
                          service_tier='standard', pricing_as_of=permit.price_verified_date),
        limits=Limits(MAX_INPUT_TOKENS, MAX_INPUT_TOKENS,
                      MAX_OUTPUT_TOKENS, 1, MAX_ESTIMATED_USD),
        counter=counter,
    )
    try:
        response = ledger.guarded_create(client, request)
    except SpendHold:
        # Model may already have run if transport failed. Never auto-retry.
        raise M12Hold('MODEL_NOT_CONFIRMED_OR_PRE_SEND_HOLD_NO_RETRY') from None
    except Exception:
        raise M12Hold('MODEL_OR_BUDGET_UNKNOWN_NO_RETRY') from None
    text = getattr(response, 'output_text', None)
    status = getattr(response, 'status', None)
    if not isinstance(text, str):
        text = ''
    # Raw response stays only in 0700 directory in a new 0600 file.
    try:
        _private_write_new(receipt_path, {
            'run_id':run_id,
            'model':MODEL,
            'request_sha256':request_sha,
            'input_sha256':input_sha,
            'remote_status':str(status)[:40],
            'raw_reply':text,
            'reply_sha256':sha256(text.encode('utf-8')).hexdigest(),
            'verified_ready': status == 'completed' and text.strip() in READY_STRINGS,
            'model_calls':ledger.calls_submitted,
            'official_count_calls':1,
            'local_spend_ledger':ledger.public_status(),
        })
    except M12Hold:
        raise M12Hold('PRIVATE_RESULT_WRITE_UNKNOWN_NO_RETRY') from None
    if status != 'completed' or text.strip() not in READY_STRINGS:
        raise M12Hold('READY_TEXT_OR_STATUS_UNVERIFIED')
    return {
        'phase':'G3_M12_FIRST_READY_ONLY',
        'status':'READY_FIRST_RESPONSE_VERIFIED',
        'mode':'LIVE_ELIGIBLE_AFTER_SEPARATE_CONSENT',
        'run_id':run_id,
        'source_sha':'VERIFIED_6_GIT_BLOBS',
        'input_sha256':input_sha,
        'request_sha256':request_sha,
        'reply_sha256':sha256(text.encode('utf-8')).hexdigest(),
        'official_count_calls':1,
        'model_calls':1,
        'next_generation_started':False,
        'private_reply_persisted':True,
        'estimated_spend_usd':ledger.public_status()['estimated_spent_usd'],
        'not_a_b_or_quality_proof':True,
    }


def main() -> None:
    """CLI is a static offline entry: NO client or API credentials can be used."""
    request, nbytes, input_sha = _single_ready_request(Path(__file__).parent / 'pinned_six')
    print(json.dumps({
        'phase':'G3_M12_PREPARED_OFFLINE_ONLY',
        'status':'LIVE_HOLD_SEPARATE_AUTHORIZATION_REQUIRED',
        'model':request['model'],
        'source_bytes':nbytes,
        'input_sha256':input_sha,
        'output_token_ceiling':request['max_output_tokens'],
        'cap_estimated_usd':str(MAX_ESTIMATED_USD),
        'official_api_count_calls':0,
        'model_api_calls':0,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
