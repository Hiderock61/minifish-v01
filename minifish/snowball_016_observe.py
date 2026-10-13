"""MiniFish READ-ONLY public Coconala request observer (SNOW-AI-016)."""
from __future__ import annotations
import json
from pathlib import Path
from minifish import Action, MiniFishRunner, ScriptedPlanner

TARGET='https://coconala.com/requests/5317978'
OUT=Path('snowball_016_capture')
OUT.mkdir(exist_ok=True)
runner=MiniFishRunner(
    ScriptedPlanner([Action(type='done',result='Read-only public listing view observed')]),
    max_steps=1,max_duration_seconds=70,headless=True,
    capture_dir=str(OUT/'captures'),log_path=str(OUT/'run.json'))
state=runner.run(goal='Read public request only; no click, login, fill, submit or payment.',start_url=TARGET)
obs=state.events[0].observation if state.events else {}
body=str(obs.get('text_excerpt','') or '')
title=str(obs.get('title','') or '')
uri=str(obs.get('url','') or TARGET)
ok=(state.status=='COMPLETED' and '日々のルーティン' in (body+title) and '1,500' in body and ('掲載漏れ' in body or 'ルーティン' in body))
kind='PUBLIC_LISTING_OBSERVED' if ok else 'BLOCKED_OR_INSUFFICIENT_EVIDENCE'
result=dict(kind=kind,run_id=state.run_id,status=state.status,steps=state.step_count,
            url=uri,title=title,raw_excerpt=body[:2200],error=state.error,
            note='Public job observation only. No seller product listings have been checked.')
(OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=[f'## 🐟 CASE016 MiniFish public listing probe',f'- Classification: **{kind}**',
       f'- Run ID: `{state.run_id}`',f'- Status: `{state.status}` / steps: {state.step_count}',
       f'- Target: {TARGET}',f'- Read URL: {uri}',
       f'- Title: {title[:160]}',f'- Error: {str(state.error or "none")[:160]}',
       '', '※ PUBLIC_LISTING_OBSERVEDは案件募集ページを読んだ意味のみ。',
       '※ 販売者の掲載実データ、販売状況、顧客台帳は未取得。応募・送信・更新なし。']
(OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
print('\n'.join(lines),flush=True)
