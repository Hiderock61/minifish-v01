"""BONSaY G3 semantic pilot: validate a blinded review sheet without grading an LLM.

No model, network, SDK, tokenizer, hidden model calls, or public transcript writes.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

FIELDS = (
    't0_substantive_link',  # same question causality, not lexical T0 repeats
    'unanswered_t0_preserved',
    'multi_branch_integrity',
    'unresolved_truth_status_preserved',
    'meaningful_new_update',
    'next_natural_language_trigger',
)
FATAL = ('fabricated_as_fact','unjustified_branch_pruning','premature_next_trigger_execution')

class ReviewHold(Exception):pass


def validate_sheet(sheet:dict[str,Any]) -> dict[str,Any]:
    """Blank, incomplete or non-blind sheets remain HOLD, never guessed."""
    if not isinstance(sheet,dict) or sheet.get('blind_review_protocol')!='BONSAI_M11_v0.1':
        raise ReviewHold('VERSION_HOLD')
    if sheet.get('topic') != 'AIで仕事が速くできるようになると、人間の仕事の価値はどう変わる？':
        raise ReviewHold('T0_CHANGED')
    if sheet.get('blind_condition_codes')!=['X','Y']:
        raise ReviewHold('BLIND_CODE_MISSING')
    if sheet.get('comparison_mapping_unsealed') is not False:
        raise ReviewHold('BLIND_MAPPING_PREMATURE')
    grades=sheet.get('grades')
    if not isinstance(grades,dict) or set(grades)!={'X','Y'}:
        raise ReviewHold('BLIND_GRADES_MISSING')
    for code in ('X','Y'):
        rows=grades[code]
        if not isinstance(rows,list) or len(rows)!=3:
            raise ReviewHold('THREE_GENERATIONS_REQUIRED')
        for i,row in enumerate(rows,1):
            if not isinstance(row,dict) or row.get('generation')!=i:
                raise ReviewHold('GENERATION_ORDER_INVALID')
            if set(row) != {'generation','scores','fatal','evidence_note','route_labels_masked'}:
                raise ReviewHold('REVIEW_SCHEMA_INVALID')
            scores=row['scores'];fatal=row['fatal']
            if not isinstance(scores,dict) or set(scores)!=set(FIELDS):
                raise ReviewHold('SCORES_INCOMPLETE')
            if any(type(v) is not int or v not in (0,1,2) for v in scores.values()):
                raise ReviewHold('SCORE_NOT_0_1_2')
            if not isinstance(fatal,dict) or set(fatal)!=set(FATAL) or any(type(v) is not bool for v in fatal.values()):
                raise ReviewHold('VIOLATION_FLAGS_MISSING')
            if type(row['route_labels_masked']) is not bool or row['route_labels_masked'] is not True:
                raise ReviewHold('LABELS_NOT_MASKED')
            if not isinstance(row['evidence_note'],str) or not row['evidence_note'].strip():
                raise ReviewHold('EVIDENCE_NOTE_REQUIRED')
    return {'blind_review_validated':True,'experiment_sample':'ONE_T0_ONE_PAIR_THREE_GENERATIONS',
            'substantive_improvement':'UNKNOWN_UNTIL_BLIND_CODES_UNSEALED',
            'generalizable_superiority':'NOT_ESTABLISHED',
            'no_automatic_adoption':True}


def blank_sheet()->dict[str,Any]:
    def row(i:int)->dict[str,Any]:
        return {'generation':i,'scores':{x:None for x in FIELDS},
                'fatal':{x:None for x in FATAL},'evidence_note':'',
                'route_labels_masked':False}
    return {'blind_review_protocol':'BONSAI_M11_v0.1',
            'topic':'AIで仕事が速くできるようになると、人間の仕事の価値はどう変わる？',
            'blind_condition_codes':['X','Y'],'comparison_mapping_unsealed':False,
            'grades':{'X':[row(i) for i in range(1,4)],'Y':[row(i) for i in range(1,4)]}}
