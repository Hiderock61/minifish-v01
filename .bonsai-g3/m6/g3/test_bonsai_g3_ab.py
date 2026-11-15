from pathlib import Path
import json
import pytest
from bonsai_g3_ab import (
    T0, SOURCES, MockTransport, run_pair, run_condition,
    structural_gate, START_PROMPT, B_ADDENDUM
)


def test_reuse_six_exact_sources():
    assert len(SOURCES) == 6
    assert all(len(blob_sha) == 40 for blob_sha in SOURCES.values())


def test_a_b_same_initial_question():
    assert T0 == 'AIで仕事が速くできるようになると、人間の仕事の価値はどう変わる？'
    assert 'T0航路チェック' not in START_PROMPT
    assert 'T0航路チェック' in B_ADDENDUM


def test_three_generations_both_branches(tmp_path):
    r=run_pair(tmp_path)
    assert r['status'] == 'MOCK_ORCHESTRATION_PASS'
    assert r['actual_ai_calls'] == 0
    assert [c['completed_generations'] for c in r['conditions']] == [3,3]
    assert all(c['semantic_gate'] == 'UNKNOWN_REAL_AI_NOT_TESTED' for c in r['conditions'])


def test_sequence_exactly_ready_t0_a_a(tmp_path):
    run_pair(tmp_path)
    for c in ['A','B']:
        turns=json.loads((tmp_path/f'{c}_MOCK_transcript.json').read_text())
        assert [e['content'] for e in turns if e['role']=='user'][1:] == [T0,'あ','あ']
        assert len(turns) == 8


def test_b_intervention_not_in_a(tmp_path):
    run_pair(tmp_path)
    a=json.loads((tmp_path/'A_MOCK_transcript.json').read_text())
    b=json.loads((tmp_path/'B_MOCK_transcript.json').read_text())
    assert a[0]['content'] == START_PROMPT
    assert b[0]['content'] == START_PROMPT + B_ADDENDUM
    assert a[2]['content'] == b[2]['content']


def test_ready_missing_stops_before_t0(tmp_path):
    class NoReady:
        def reply(self,c,h): return 'Not ready'
    r=run_condition('A',NoReady(),tmp_path)
    assert r.completed_generations == 0
    assert r.status == 'MOCK_STOP'
    turns=json.loads((tmp_path/'A_MOCK_transcript.json').read_text())
    assert len([t for t in turns if t['role']=='user']) == 1


def test_transport_failure_stops_without_extra_a(tmp_path):
    class Broken:
        def reply(self,c,h):
            if len(h)==1: return '🎭 BONSaY 現行候補 v0.1d｜READY'
            return ''
    r=run_condition('B',Broken(),tmp_path)
    assert r.completed_generations == 0
    assert r.status == 'MOCK_STOP'


def test_missing_next_trigger_does_not_advance(tmp_path):
    class NoNext:
        def reply(self,c,h):
            if len(h)==1: return '🎭 BONSaY 現行候補 v0.1d｜READY'
            return '🌳 🆕 🌿 STOP'
    r=run_condition('A',NoNext(),tmp_path)
    assert r.completed_generations == 0
    assert 'structure_markers_missing' in r.reason


def test_structure_markers_are_not_semantic_proof():
    assert structural_gate('🌳 🆕 🌿 次の更新トリガー')
    # This can be meaningless: never turn marker presence into SEMANTIC_PASS.


def test_real_mode_not_available_and_no_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','TEST_DO_NOT_USE')
    r=run_pair(tmp_path)
    assert r['actual_ai_calls'] == 0
    assert r['live_ab_status'] == 'NOT_PERFORMED'
    assert 'TEST_DO_NOT_USE' not in (tmp_path/'mock_result.json').read_text()


def test_wrong_generation_count_rejected(tmp_path):
    with pytest.raises(ValueError): run_condition('A',MockTransport(),tmp_path,generations=4)
