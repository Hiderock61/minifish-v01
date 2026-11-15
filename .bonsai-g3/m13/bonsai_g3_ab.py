"""BONSaY P1/G3 offline-only A/B transport acceptance harness.

This intentionally cannot call external AI services, open browsers, use tokens, or write to GitHub.
It verifies orchestration mechanics, NOT BONSaY semantic improvement.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Protocol
import argparse
import json
import uuid

START_URL = 'https://github.com/Hiderock61/hiderock-method-os/blob/main/BONSAI_CURRENT_START.md'
T0 = 'AIで仕事が速くできるようになると、人間の仕事の価値はどう変わる？'
START_PROMPT = f'このURLを読んでBONSaYを起動してください。読み込みが終わったら勝手にテーマを始めず、READYだけ返して待ってください。\n\n{START_URL}'
READY_STRINGS = {
    '🎭 BONSaY 現行候補 v0.1d｜READY',
    '🎭 BONSaY 公演ランタイム候補 v0.1d｜READY',
}
# This is a *candidate* intervention. Existing v0.5 and v0.1d stay frozen.
B_ADDENDUM = '''\n\n【隔離A/B試験専用・T0航路チェック候補】
通常のBONSaYの枝生存判定・ヒデロコ・世代STOPは変えない。
各世代の最後で、次のC-IDEAと最初のT0との関係を「直結／一部補完／独立派生」のいずれかで明示し、理由と元T0の未回答部分を短く示す。
関連の薄い枝を機械的に剪定せず、元T0へ強制リセットしない。
この追加表示は検査用であり、原本へ正式採用しない。原典を読み込めなければREADYを返さず停止する。'''
SOURCES = {
    'BONSAI_START_HERE.md':'5b4c6a116a85402c677827baf4136762c53903eb',
    'methods/006_hiderock-gekidan-method.md':'f76790bdc65f260558a1283cf84d4bd0001567ee',
    'methods/006A_hiderock-gekidan-roster.md':'031938a9150c08632eddb36014170cb3e287db61',
    'methods/006B_hiderock-gekidan-emoji-legend.md':'b2df1ae68320d14b7f5678f248923175a387c628',
    'methods/006C_hideroko-injection-protocol.md':'f98367ec4a05895fadff657d954b1f3fb9096365',
    'experiments/bonsai-performance-runtime-v0.1d-candidate.md':'2e8649b33088eeb74ea2ac38e5a4663d3877b498',
}

class TurnTransport(Protocol):
    def reply(self, condition: str, history: list[dict]) -> str: ...

@dataclass
class ConditionReport:
    condition: str
    status: str
    reason: str | None
    requested_generations: int
    completed_generations: int
    source_read_proof: str
    transcript_sha256: str
    transcript_file: str | None
    structure_gate: str
    semantic_gate: str

class MockTransport:
    """Synthetic responses for transport/STOP acceptance; NOT AI-generated evidence."""
    def reply(self, condition: str, history: list[dict]) -> str:
        last = history[-1]['content']
        if len(history) == 1 and 'READY' in last:
            return '🎭 BONSaY 現行候補 v0.1d｜READY'
        prior_assistant = sum(1 for item in history if item['role'] == 'assistant')
        if prior_assistant < 1 or (prior_assistant > 1 and last != 'あ'):
            raise ValueError('invalid_session_transition')
        generation = prior_assistant
        suffix = ('\n🧭航路：一部補完（模擬表示）｜元T0の未回答：社会的価値') if condition == 'B' else ''
        return (f'【模擬応答・内容評価対象外】🌳 C-IDEA{generation}｜現在の更新トリガー\n'
                '🎭役A｜反応元：現在のトリガー｜🆕新しい尺度を観測\n'
                '🎭役B｜反応元：現在のトリガー｜🆕別の条件を観測\n'
                '🌳枝生存判定©️｜🌿観測Aを継続｜⚔️観測Bは未確定\n'
                f'🌳 C-IDEA{generation+1}｜次の更新トリガー\n'
                '「残された尺度と条件の関係はどう変わるか？」\nSTOP' + suffix)


def structural_gate(text: str) -> bool:
    # Only a cheap marker sanity check: same-reaction-source and meaning require independent audit.
    return all(marker in text for marker in ('🌳', '🆕', '🌿', '次の更新トリガー'))


def run_condition(condition: str, transport: TurnTransport, outdir: Path,
                  generations: int = 3) -> ConditionReport:
    if condition not in ('A', 'B') or generations not in (3, 5):
        raise ValueError('unsupported_experiment')
    history: list[dict] = []
    start = START_PROMPT + (B_ADDENDUM if condition == 'B' else '')
    completed, reason = 0, None
    def exchange(user_text: str) -> str:
        history.append({'role':'user','content':user_text})
        answer = transport.reply(condition, list(history))
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('empty_response')
        history.append({'role':'assistant','content':answer})
        return answer
    try:
        ready = exchange(start)
        if ready.strip() not in READY_STRINGS:
            raise ValueError('ready_not_verified')
        for i in range(generations):
            response = exchange(T0 if i == 0 else 'あ')
            if not structural_gate(response):
                raise ValueError(f'generation_{i+1}_structure_markers_missing')
            if 'STOP' not in response:
                raise ValueError(f'generation_{i+1}_stop_marker_missing')
            completed += 1
    except Exception as exc:
        reason = type(exc).__name__ + ':' + str(exc)
    status = 'MOCK_SEQUENCE_PASS' if completed == generations and reason is None else 'MOCK_STOP'
    transcript = json.dumps(history, ensure_ascii=False, indent=2)
    outdir.mkdir(parents=True, exist_ok=True)
    # Explicitly mock transcripts: never publish an authenticated user's actual conversation.
    path = outdir / f'{condition}_MOCK_transcript.json'
    path.write_text(transcript, encoding='utf-8')
    return ConditionReport(
        condition, status, reason, generations, completed,
        'SIMULATED_ONLY_NO_REAL_GITHUB_READ', sha256(transcript.encode()).hexdigest(),
        path.name, 'MOCK_MARKER_SEQUENCE_ONLY' if status == 'MOCK_SEQUENCE_PASS' else 'HOLD',
        'UNKNOWN_REAL_AI_NOT_TESTED')


def run_pair(outdir: Path, transport: TurnTransport | None = None) -> dict:
    transport = transport if transport is not None else MockTransport()
    reports = [run_condition(c, transport, outdir) for c in ('A', 'B')]
    report = {
        'project': 'BONSaY P1 G3 T0航路チェック',
        'mode':'OFFLINE_MOCK_ONLY',
        'created_at':datetime.now(timezone.utc).isoformat(),
        'run_id':'g3mock_'+uuid.uuid4().hex[:12],
        'source_manifest': SOURCES,
        'fixed_t0': T0,
        'conditions': [asdict(r) for r in reports],
        'human_semantic_verdict': 'UNKNOWN_PENDING_BLIND_REVIEW',
        'actual_ai_calls': 0,
        'web_browser_calls': 0,
        'external_writes': 0,
        'status': 'MOCK_ORCHESTRATION_PASS' if all(x.status=='MOCK_SEQUENCE_PASS' for x in reports) else 'HOLD',
        'live_ab_status': 'NOT_PERFORMED',
    }
    (outdir/'mock_result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--outdir',default='evidence')
    args=parser.parse_args()
    result=run_pair(Path(args.outdir))
    # Public-safe summary, never raw transcript
    print(json.dumps({k:v for k,v in result.items() if k not in ('conditions','source_manifest')},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
