"""G3-M1 isolated, fail-closed spend/source gate for the existing G3 transport.

No external API or network operations, account introspection, or credential reads.
TokenCounter is injected. A local/mock count NEVER authorizes a live request.

This module does not claim that an API token-count receipt is an invoice-level
hard cap, nor that source SHA verification proves model comprehension.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Protocol
import json

from bonsai_g3_ab import SOURCES
from bonsai_g3_transport import (
    ExecutionHold, SourceHold, SourceBundle, git_blob_sha,
    read_pinned_sources, run_pair, TransportSettings,
)


class SpendHold(ExecutionHold):
    """Stop before model submission when count, usage, or budget is uncertain."""


def payload_digest(request: dict[str, Any]) -> str:
    """Ties a count receipt to the exact outbound model request payload."""
    return sha256(json.dumps(request, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class TokenCountReceipt:
    model: str
    request_sha256: str
    input_tokens: int
    method: str  # 'official_responses_input_tokens' or 'offline_simulation'


class TokenCounter(Protocol):
    def count(self, request: dict[str, Any]) -> TokenCountReceipt: ...


@dataclass(frozen=True)
class FrozenPrice:
    model: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    service_tier: str = 'standard'
    pricing_as_of: str = '2026-11-15'

    def validate(self) -> None:
        if not self.model or not self.service_tier:
            raise SpendHold('PRICE_MODEL_OR_TIER_MISSING')
        if any(x.is_nan() or not x.is_finite() or x <= 0 for x in
               (self.input_usd_per_million, self.output_usd_per_million)):
            raise SpendHold('PRICE_INVALID')


@dataclass(frozen=True)
class Limits:
    max_input_tokens_per_call: int
    max_input_tokens_total: int
    max_output_tokens_per_call: int
    max_calls: int
    max_estimated_usd: Decimal

    def validate(self) -> None:
        if (self.max_input_tokens_per_call <= 0 or self.max_input_tokens_total <= 0
                or self.max_output_tokens_per_call <= 0 or not 1 <= self.max_calls <= 8
                or not self.max_estimated_usd.is_finite()
                or self.max_estimated_usd <= 0):
            raise SpendHold('LIMITS_INVALID')


@dataclass
class SpendLedger:
    """Shared between A and B. Fields are estimates, never actual billing."""
    mode: str
    price: FrozenPrice
    limits: Limits
    counter: TokenCounter
    calls_submitted: int = 0
    input_tokens_counted: int = 0
    output_tokens_observed: int = 0
    estimated_spent_usd: Decimal = Decimal('0')
    uncertain_reserved_usd: Decimal = Decimal('0')
    frozen: bool = False
    last_hold_reason: str | None = None
    receipts: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.price.validate()
        self.limits.validate()
        if self.mode not in ('offline_mock', 'live'):
            raise SpendHold('INVALID_MODE')

    def hold(self, code: str) -> None:
        self.frozen = True
        self.last_hold_reason = code
        raise SpendHold(code)

    def _cost(self, inp: int, out: int) -> Decimal:
        return ((Decimal(inp) * self.price.input_usd_per_million +
                 Decimal(out) * self.price.output_usd_per_million) / Decimal(1_000_000))

    @staticmethod
    def _usage(response: Any) -> tuple[int, int] | None:
        u = getattr(response, 'usage', None)
        a = getattr(u, 'input_tokens', None)
        b = getattr(u, 'output_tokens', None)
        if type(a) is int and type(b) is int and a >= 0 and b >= 0:
            return a, b
        return None

    def guarded_create(self, client: Any, request: dict[str, Any]) -> Any:
        """Exactly one count then at most one send; freeze after any ambiguity."""
        if self.frozen:
            self.hold('LEDGER_FROZEN')
        if set(request) != {'model', 'input', 'max_output_tokens', 'store'}:
            self.hold('REQUEST_SCHEMA_MISMATCH')
        if request['model'] != self.price.model:
            self.hold('MODEL_PRICE_MISMATCH')
        if request['store'] is not False:
            self.hold('STORE_MUST_BE_FALSE')
        ceiling = request['max_output_tokens']
        if type(ceiling) is not int or ceiling < 1 or ceiling > self.limits.max_output_tokens_per_call:
            self.hold('OUTPUT_CEILING_EXCEEDED')
        if self.calls_submitted >= self.limits.max_calls:
            self.hold('TOTAL_CALL_CAP_REACHED')
        if not isinstance(request['input'], list) or not request['input']:
            self.hold('INPUT_INVALID')

        digest = payload_digest(request)
        try:
            rec = self.counter.count(dict(request))
        except Exception:
            self.hold('TOKEN_COUNT_UNAVAILABLE')
        if (rec.model != self.price.model or rec.request_sha256 != digest or
                type(rec.input_tokens) is not int or rec.input_tokens <= 0):
            self.hold('TOKEN_COUNT_RECEIPT_INVALID')
        if self.mode == 'live' and rec.method != 'official_responses_input_tokens':
            self.hold('OFFICIAL_EXACT_TOKEN_COUNT_REQUIRED')
        if self.mode == 'offline_mock' and rec.method != 'offline_simulation':
            self.hold('MOCK_COUNTER_METHOD_REQUIRED')
        if rec.input_tokens > self.limits.max_input_tokens_per_call:
            self.hold('SINGLE_CALL_INPUT_TOKEN_CAP')
        if self.input_tokens_counted + rec.input_tokens > self.limits.max_input_tokens_total:
            self.hold('TOTAL_INPUT_TOKEN_CAP')
        worst_case = self._cost(rec.input_tokens, ceiling)
        available = self.limits.max_estimated_usd - (self.estimated_spent_usd + self.uncertain_reserved_usd)
        if worst_case > available:
            self.hold('PRE_SEND_ESTIMATED_SPEND_CAP')

        # Reserve an entire request (including the requested output ceiling),
        # BEFORE transmitting. After transport errors, assume it might be billed.
        self.calls_submitted += 1
        self.input_tokens_counted += rec.input_tokens
        meta = {'request_sha256':digest, 'count_method':rec.method,
                'counted_input_tokens':rec.input_tokens,
                'requested_output_ceiling':ceiling, 'reserved_usd':str(worst_case)}
        try:
            response = client.responses.create(**request)
        except Exception:
            self.uncertain_reserved_usd += worst_case
            self.receipts.append(dict(meta, result='DELIVERY_UNKNOWN', usage='UNKNOWN'))
            self.hold('MODEL_TRANSPORT_UNKNOWN_NO_RETRY')
        usage = self._usage(response)
        if usage is None:
            self.uncertain_reserved_usd += worst_case
            self.receipts.append(dict(meta, result='USAGE_MISSING', usage='UNKNOWN'))
            self.hold('USAGE_UNAVAILABLE_NO_FURTHER_CALLS')
        a, b = usage
        if a > rec.input_tokens or b > ceiling:
            self.uncertain_reserved_usd += worst_case
            self.receipts.append(dict(meta, result='USAGE_EXCEEDS_RESERVATION',
                                      usage={'input':a, 'output':b}))
            self.hold('USAGE_EXCEEDS_PRE_SEND_RESERVATION')
        computed = self._cost(a, b)
        self.estimated_spent_usd += computed
        self.output_tokens_observed += b
        self.receipts.append(dict(meta, result='USAGE_RECORDED',
                                  observed_input_tokens=a, observed_output_tokens=b,
                                  estimated_usd=str(computed)))
        return response

    def public_status(self) -> dict[str, Any]:
        """No prompts, credentials, raw output, account identifiers, or pricing guarantee."""
        return {'mode':self.mode, 'model':self.price.model, 'service_tier':self.price.service_tier,
                'pricing_as_of':self.price.pricing_as_of,
                'submitted_calls':self.calls_submitted,
                'counted_input_tokens':self.input_tokens_counted,
                'observed_output_tokens':self.output_tokens_observed,
                'estimated_spent_usd':str(self.estimated_spent_usd),
                'uncertain_reserved_usd':str(self.uncertain_reserved_usd),
                'cap_estimated_usd':str(self.limits.max_estimated_usd),
                'last_hold_reason':self.last_hold_reason,
                'frozen':self.frozen,
                'token_receipts':list(self.receipts),
                'not_invoice_or_account_hard_cap':True}


class GuardedClient:
    def __init__(self, raw_client: Any, ledger: SpendLedger):
        self.raw_client = raw_client
        self.ledger = ledger
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        return self.ledger.guarded_create(self.raw_client, kwargs)


def require_official_local_sources(source_root: Path) -> SourceBundle:
    """REAL pinned bytes required for both offline preflight and any live run.

    Fail closed if files are unavailable. Remote SHA receipts without actual
    bytes are not a substitute for local materialization.
    """
    bundle = read_pinned_sources(source_root, SOURCES)
    # Recheck decoded text, not just the manifest boolean.
    for path, expected in SOURCES.items():
        if git_blob_sha(bundle.texts[path].encode('utf-8')) != expected:
            raise SourceHold('LOCAL_CONTENT_SHA_MISMATCH')
    return bundle


def inspect_local_sources(source_root: Path) -> dict[str, Any]:
    """Inspection only; never downloads or edits the source directory."""
    try:
        bundle = require_official_local_sources(source_root)
    except (SourceHold, OSError) as exc:
        return {'status':'LOCAL_SOURCE_HOLD', 'reason':str(exc), 'files_validated':0}
    return {'status':'LOCAL_SOURCE_6_OF_6_PASS', 'files_validated':len(bundle.texts),
            'utf8_bytes':sum(len(x.encode('utf8')) for x in bundle.texts.values()),
            'sha_match':True}


def run_checked_pair(*, source_root: Path, client_factory: Callable[[], Any] | None,
                     settings: TransportSettings, ledger: SpendLedger,
                     private_dir: Path) -> dict[str, Any]:
    """A/B paired execution. Only callable with six original local source bytes.

    Live consent, key validity, billing and current model permissions remain
    separate independent gates. Does NOT automatically launch in this package.
    """
    if settings.mode != ledger.mode or settings.model != ledger.price.model:
        ledger.hold('SETTINGS_LEDGER_MISMATCH')
    settings.check()
    # Offline code is intentionally *incapable* of receiving an SDK client
    # through this high-level entry point. Prevent a mislabeled mock from
    # accidentally billing a live account.
    if settings.mode == 'offline_mock':
        if client_factory is not None:
            ledger.hold('OFFLINE_EXTERNAL_CLIENT_FACTORY_FORBIDDEN')
        actual_factory = OfflineMultiTurnClient
    else:
        if client_factory is None:
            ledger.hold('LIVE_CLIENT_FACTORY_REQUIRED')
        actual_factory = client_factory
    bundle = require_official_local_sources(source_root)
    def guarded_factory() -> GuardedClient:
        return GuardedClient(actual_factory(), ledger)
    report = run_pair(guarded_factory, settings, bundle, private_dir)
    report['M1_shared_budget'] = ledger.public_status()
    report['M1_local_sources'] = 'VERIFIED_6_BLOBS'
    return report


class OfflineMultiTurnClient:
    """Local deterministic text fixture, never talks to a network or SDK.

    This fixture is used by the top-level `offline_mock` A/B runner instead of
    accepting an arbitrary client factory that might secretly bill an API.
    """
    def __init__(self):
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        from types import SimpleNamespace
        self.calls.append(kwargs)
        n=len(self.calls)
        if n==1:
            text='🎭 BONSaY 現行候補 v0.1d｜READY'
        else:
            index=n-1
            text=(f'【ローカル模擬・非AI】🌳 C-IDEA{index}｜更新トリガー\n'
                  f'🎭役A 反応元C-IDEA{index} 🆕独立観測A\n'
                  f'🎭役B 反応元C-IDEA{index} 🆕独立観測B\n'
                  '🌳枝生存判定©️ 🌿模擬生存 ⚔️模擬未解決\n'
                  f'🌳次の更新トリガー C-IDEA{index+1}\n'
                  '「別の条件からの観測はどうなるか？」（模擬停止）')
        return SimpleNamespace(status='completed', output_text=text,
                               usage=SimpleNamespace(input_tokens=1500, output_tokens=300))


class OfficialResponsesInputCounter:
    """Optional future live-only official count adapter. NEVER instantiated by default.

    A caller must supply an already-authorized SDK client. This class neither
    obtains credentials nor starts a session. Calling count() DOES contact the
    external token-count endpoint and requires separate user approval.
    """
    def __init__(self, sdk_client: Any, *, authorized: bool = False):
        if not authorized:
            raise SpendHold('OFFICIAL_COUNT_API_REQUIRES_SEPARATE_AUTHORIZATION')
        self.client = sdk_client

    def count(self, request: dict[str, Any]) -> TokenCountReceipt:
        if set(request) != {'model', 'input', 'max_output_tokens', 'store'}:
            raise SpendHold('UNSUPPORTED_OFFICIAL_COUNTER_REQUEST_SHAPE')
        # Count with exactly the model+input of the request being sent.
        # max_output_tokens and store do not add input context tokens.
        result = self.client.responses.input_tokens.count(
            model=request['model'], input=request['input'])
        number = getattr(result, 'input_tokens', None)
        if type(number) is not int or number <= 0:
            raise SpendHold('OFFICIAL_COUNTER_NO_VALID_TOKEN_COUNT')
        return TokenCountReceipt(request['model'], payload_digest(request),
                                 number, 'official_responses_input_tokens')


class OfflineTestCounter:
    """Predictable fixture. Never valid for live; no actual token counting."""
    def __init__(self, tokens: int = 1500):
        self.tokens = tokens
        self.calls = 0

    def count(self, request: dict[str, Any]) -> TokenCountReceipt:
        self.calls += 1
        return TokenCountReceipt(request['model'], payload_digest(request),
                                 self.tokens, 'offline_simulation')


def default_offline_ledger(*, counter: TokenCounter | None = None) -> SpendLedger:
    """Test values only. Frozen 2026-11-15 price does not assert current price."""
    return SpendLedger(
        mode='offline_mock',
        price=FrozenPrice('gpt-6-luna', Decimal('0.10'), Decimal('0.50')),
        limits=Limits(max_input_tokens_per_call=50000,
                      max_input_tokens_total=400000,
                      max_output_tokens_per_call=3000,
                      max_calls=8,
                      max_estimated_usd=Decimal('0.05')),
        counter=counter or OfflineTestCounter(),
    )
