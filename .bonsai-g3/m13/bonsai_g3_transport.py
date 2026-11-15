"""BONSaY G3 isolated multi-turn Responses transport, no automatic live execution.

No credentials are read. The caller must inject an API-shaped client. Genuine
network usage is separately gated by owner consent and an environment switch.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any, Mapping
import json
import os
import stat
import uuid

from bonsai_g3_ab import START_PROMPT, T0, SOURCES, B_ADDENDUM, READY_STRINGS, structural_gate

MAX_FILE_BYTES = 160_000
MAX_INPUT_BYTES = 900_000
DEFAULT_OUTPUT_TOKENS = 3_000
MAX_REQUESTS_PER_CONDITION = 4


class SourceHold(Exception):
    """Missing, unreadable or unverified original. No model call may occur."""


class ExecutionHold(Exception):
    """Preflight / consent / private-storage error. No retry permitted."""


def git_blob_sha(data: bytes) -> str:
    header = f'blob {len(data)}\0'.encode('ascii')
    return sha1(header + data).hexdigest()


@dataclass(frozen=True)
class SourceBundle:
    texts: Mapping[str, str]
    manifest: Mapping[str, str]
    verified: bool


def read_pinned_sources(root: Path, manifest: Mapping[str, str] = SOURCES) -> SourceBundle:
    """Read exact pinned Git blobs from a private/local source directory.

    Does NOT fetch GitHub. Receipt proves byte identity locally, not that an LLM
    comprehended the text or that the remote repo still has the same HEAD.
    """
    if set(manifest) != set(SOURCES):
        raise SourceHold('source_manifest_path_set_mismatch')
    try:
        parent = Path(root).resolve(strict=True)
        if not parent.is_dir():
            raise SourceHold('source_root_not_directory')
        texts: dict[str, str] = {}
        total = 0
        for relative, expected in manifest.items():
            if len(expected) != 40 or any(c not in '0123456789abcdef' for c in expected):
                raise SourceHold('invalid_manifest_sha')
            candidate = parent / relative
            # A symlink at the leaf or an escaped intermediate path is refused.
            if candidate.is_symlink():
                raise SourceHold('source_symlink_refused')
            full = candidate.resolve(strict=True)
            if not full.is_relative_to(parent) or not full.is_file():
                raise SourceHold('source_outside_pinned_root')
            data = full.read_bytes()
            if not data or len(data) > MAX_FILE_BYTES:
                raise SourceHold('source_size_invalid')
            total += len(data)
            if total > MAX_INPUT_BYTES:
                raise SourceHold('aggregate_source_size_invalid')
            if git_blob_sha(data) != expected:
                raise SourceHold(f'git_blob_mismatch:{relative}')
            texts[relative] = data.decode('utf-8')
        return SourceBundle(texts=texts, manifest=dict(manifest), verified=True)
    except SourceHold:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceHold('unavailable_or_unreadable_source:' + type(exc).__name__) from None


def _instructions(bundle: SourceBundle) -> str:
    if not bundle.verified or set(bundle.texts) != set(SOURCES):
        raise SourceHold('unverified_source_bundle')
    sections = [
        '次はBONSaY六原典の検証済み全文です。原典を越える確定情報を推測しない。',
        '公演開始前はREADYのみ。世代末尾で次トリガーを出して停止。',
        'この実験では原典本文を勝手に変更・採用せず、与えた発言を入力として扱う。'
    ]
    for path in SOURCES:
        sections.append(f'\n===== BEGIN {path} (git-blob {bundle.manifest[path]}) =====\n'
                        + bundle.texts[path] + f'\n===== END {path} =====')
    result = '\n'.join(sections)
    if len(result.encode('utf-8')) > MAX_INPUT_BYTES:
        raise SourceHold('source_context_size_invalid')
    return result


@dataclass(frozen=True)
class TransportSettings:
    model: str
    mode: str = 'offline_mock'  # offline_mock or live
    allow_billable: bool = False
    output_tokens: int = DEFAULT_OUTPUT_TOKENS

    def check(self) -> None:
        if not self.model.strip() or len(self.model) > 120:
            raise ExecutionHold('model_required')
        if self.mode not in ('offline_mock', 'live'):
            raise ExecutionHold('unsupported_transport_mode')
        if not (512 <= self.output_tokens <= 4096):
            raise ExecutionHold('invalid_token_ceiling')
        if self.mode == 'live':
            # A chat 'あ' and/or an existing API key alone are NOT authorization.
            if not self.allow_billable or os.getenv('MINIFISH_G3_REAL_API_CONSENT') != 'yes':
                raise ExecutionHold('live_requires_separate_owner_consent')


@dataclass
class TurnReceipt:
    ordinal: int
    kind: str
    input_sha256: str
    response_sha256: str
    remote_status: str
    tokens_in: int | None
    tokens_out: int | None
    time_utc: str
    error_layer: str | None = None


@dataclass
class SessionResult:
    condition: str
    status: str
    reason: str | None
    completed_generations: int
    calls: int
    mode: str
    source_status: str
    structure_status: str
    semantic_status: str
    receipts: list[TurnReceipt] = field(default_factory=list)
    transcript_sha256: str | None = None

    def public_summary(self) -> dict:
        # No raw transcript, prompt, response IDs, access tokens or exception messages.
        return {
            'condition': self.condition, 'status': self.status,
            'reason': self.reason, 'completed_generations': self.completed_generations,
            'calls': self.calls, 'mode': self.mode, 'source_status': self.source_status,
            'structure_status': self.structure_status,
            'semantic_status': self.semantic_status,
            'transcript_sha256': self.transcript_sha256,
            'receipts': [asdict(x) for x in self.receipts],
        }


def _private_folder(folder: Path) -> Path:
    p = Path(folder)
    if p.exists() and p.is_symlink():
        raise ExecutionHold('private_dir_symlink_refused')
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (stat.S_IMODE(p.stat().st_mode) & 0o077) != 0:
        raise ExecutionHold('private_dir_permissions_too_open')
    return p


def _private_json(folder: Path, filename: str, obj: Any) -> Path:
    p = _private_folder(folder) / filename
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(p), flags, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception:
        p.unlink(missing_ok=True)
        raise
    return p


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token(usage: Any, key: str) -> int | None:
    value = getattr(usage, key, None)
    return value if isinstance(value, int) and value >= 0 else None


def run_session(condition: str, client: Any, settings: TransportSettings,
                bundle: SourceBundle, private_dir: Path) -> SessionResult:
    """One isolated A or B conversation, at most 4 requests; no retry.

    The client must expose responses.create(...), as in the OpenAI SDK.
    Completed delivery does not imply structural or semantic validity.
    """
    if condition not in ('A', 'B'):
        raise ExecutionHold('condition_must_be_A_or_B')
    settings.check()  # check BEFORE any network call or evidence write
    # A test-only manifest cannot silently become a live production source.
    if settings.mode == 'live' and dict(bundle.manifest) != SOURCES:
        raise SourceHold('live_requires_six_official_pinned_blob_shas')
    developer = _instructions(bundle)
    history: list[dict[str, str]] = []
    audit: list[TurnReceipt] = []
    count = 0
    completed = 0
    failure = None
    marker_count = 0
    source_status = 'LOCAL_GIT_BLOB_VERIFIED_AND_SENT_MODEL_READ_NOT_PROVEN'
    private_dir = _private_folder(private_dir)

    # B is *only* the additive experiment from v0.1, not a modified source.
    inputs = [START_PROMPT + (B_ADDENDUM if condition == 'B' else ''), T0, 'あ', 'あ']
    for i, user_text in enumerate(inputs):
        if count >= MAX_REQUESTS_PER_CONDITION:
            failure = 'REQUEST_CAP'; break
        history.append({'role': 'user', 'content': user_text})
        call_input = [{'role': 'developer', 'content': developer}] + list(history)
        input_str = json.dumps(call_input, ensure_ascii=False, separators=(',', ':'))
        if len(input_str.encode('utf-8')) > MAX_INPUT_BYTES:
            failure = 'INPUT_TOO_LONG'; break
        try:
            count += 1
            response = client.responses.create(
                model=settings.model, input=call_input,
                max_output_tokens=settings.output_tokens, store=False,
            )
        except Exception as exc:
            # API errors may contain request/user secrets. Never propagate their text.
            failure = 'TRANSPORT_UNKNOWN_' + type(exc).__name__
            audit.append(TurnReceipt(i + 1, 'READY' if i == 0 else f'GEN{i}',
                                     sha256(input_str.encode()).hexdigest(), '', 'UNKNOWN',
                                     None, None, _utc(), failure))
            break
        text = getattr(response, 'output_text', None)
        status = str(getattr(response, 'status', 'unknown'))
        if not isinstance(text, str):
            text = ''
        usage = getattr(response, 'usage', None)
        audit.append(TurnReceipt(i + 1, 'READY' if i == 0 else f'GEN{i}',
                                 sha256(input_str.encode()).hexdigest(), sha256(text.encode()).hexdigest(),
                                 status, _token(usage, 'input_tokens'),
                                 _token(usage, 'output_tokens'), _utc()))
        history.append({'role': 'assistant', 'content': text})
        if status != 'completed' or not text.strip():
            failure = 'EMPTY_OR_INCOMPLETE_RESPONSE'; break
        if i == 0:
            if text.strip() not in READY_STRINGS:
                failure = 'READY_UNVERIFIED'; break
            continue
        if not structural_gate(text):
            failure = f'GEN{i}_STRUCTURE_MARKERS_ABSENT'; break
        # No exact STOP word requirement: BONSaY v0.1d may stop implicitly.
        marker_count += 1
        completed += 1

    state = 'DELIVERY_COMPLETE_AUDIT_PENDING' if completed == 3 and not failure else 'HOLD'
    result = SessionResult(condition, state, failure, completed, count, settings.mode,
                           source_status, 'MARKERS_ONLY_NOT_FULL_QA' if marker_count else 'UNKNOWN',
                           'UNKNOWN_NOT_INDEPENDENTLY_EVALUATED', audit)
    transcript = {'condition': condition, 'mode': settings.mode, 'model': settings.model,
                  'source_manifest': dict(bundle.manifest), 'source_status': source_status,
                  'history': history, 'result': result.public_summary()}
    json_bytes = json.dumps(transcript, ensure_ascii=False, indent=2).encode('utf-8')
    result.transcript_sha256 = sha256(json_bytes).hexdigest()
    # Only a private file contains the generated conversation. No public Issue writes.
    _private_json(private_dir, f'{condition}_PRIVATE_transcript.json', transcript)
    _private_json(private_dir, f'{condition}_PUBLIC_SAFE_summary.json', result.public_summary())
    return result


def run_pair(client_factory: Any, settings: TransportSettings,
             bundle: SourceBundle, private_dir: Path) -> dict:
    """Factory creates independent A and B clients; never shares session state."""
    settings.check()
    _instructions(bundle)
    parent = _private_folder(private_dir)
    rid = 'g3_' + uuid.uuid4().hex[:12]
    client_a = client_factory()
    client_b = client_factory()
    if client_a is client_b:
        raise ExecutionHold('independent_session_clients_required')
    a = run_session('A', client_a, settings, bundle, parent / (rid + '_A'))
    b = run_session('B', client_b, settings, bundle, parent / (rid + '_B'))
    report = {
        'run_id': rid, 'mode': settings.mode,
        'A': a.public_summary(), 'B': b.public_summary(),
        'independent_client_instances': True,
        'structural_and_semantic_comparison': 'PENDING_INDEPENDENT_BLIND_AUDIT',
        'source_status': 'VERIFIED_LOCALLY_NOT_REMOTE_FETCH_RECEIPT',
        'original_g2_adapter_modified': False,
    }
    _private_json(parent, rid + '_PUBLIC_SAFE_pair.json', report)
    return report
