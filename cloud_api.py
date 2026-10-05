from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any
import os
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from minifish import Action, ScriptedPlanner, MiniFishRunner

app = FastAPI(title="MiniFish Cloud v0.1")

RUNS: dict[str, dict[str, Any]] = {}
RUNS_LOCK = Lock()
RUN_ROOT = Path(os.getenv("MINIFISH_RUN_ROOT", "/tmp/minifish-runs"))

DEMO_HTML = r"""
<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>MiniFish Cloud Demo</title></head>
<body>
  <h1>MiniFish Cloud Demo</h1>
  <button id="open-profile">プロフィール</button>
  <script>
    document.getElementById('open-profile').addEventListener('click', () => {
      location.hash = 'profile';
      document.body.innerHTML = `
        <h1>プロフィール編集</h1>
        <label for="display-name">表示名</label>
        <input id="display-name" aria-label="表示名" type="text">
        <button id="save">保存</button>`;
      document.getElementById('save').addEventListener('click', () => {
        const name = document.getElementById('display-name').value;
        location.hash = 'saved';
        document.body.innerHTML = `<h1>保存完了</h1><p>${name}</p>`;
      });
    });
  </script>
</body>
</html>
"""

CONTROL_HTML = r"""
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>MiniFish Cloud v0.1</title>
  <style>
    :root { color-scheme: dark; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    body { margin:0; background:#0b1020; color:#eef3ff; }
    main { max-width:720px; margin:0 auto; padding:calc(20px + env(safe-area-inset-top)) 18px 40px; }
    .eyebrow { color:#8ba6ff; font-size:13px; font-weight:700; letter-spacing:.12em; }
    h1 { font-size:32px; margin:8px 0 6px; }
    .sub { color:#aab6d3; margin:0 0 22px; line-height:1.55; }
    .card { background:#141c31; border:1px solid #263454; border-radius:18px; padding:16px; margin:14px 0; }
    label { display:block; font-size:13px; color:#9fb0d3; margin-bottom:7px; }
    textarea { width:100%; min-height:90px; box-sizing:border-box; border-radius:12px; border:1px solid #34476f; background:#0f172a; color:#f8fbff; padding:12px; font-size:16px; }
    button { width:100%; border:0; border-radius:13px; padding:14px 16px; font-size:17px; font-weight:800; background:#7ea1ff; color:#071025; }
    button:disabled { opacity:.5; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .metric { background:#0f172a; border-radius:12px; padding:12px; }
    .metric b { display:block; font-size:12px; color:#8ea0c5; margin-bottom:6px; }
    .metric span { font-size:18px; font-weight:800; word-break:break-word; }
    .ok { color:#78e6a0; }
    .bad { color:#ff8e8e; }
    .run { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:#9aabd0; overflow-wrap:anywhere; }
    .event { border-top:1px solid #263454; padding:12px 0; }
    .event:first-child { border-top:0; }
    .event strong { display:block; margin-bottom:5px; }
    .muted { color:#91a0bf; font-size:13px; }
  </style>
</head>
<body>
<main>
  <div class="eyebrow">MINIFISH CLOUD v0.1</div>
  <h1>iPhone操縦席 🐟</h1>
  <p class="sub">この第一段階は、iPhone → Cloud API → Playwright → Chromium → RESULT の配線を実物で確認する安全なDemo Worker。</p>

  <section class="card">
    <label for="goal">GOAL</label>
    <textarea id="goal">プロフィール編集画面を開き、表示名をヒデロックにして保存する</textarea>
    <div style="height:12px"></div>
    <button id="runButton">MiniFishを動かす</button>
  </section>

  <section class="card">
    <div class="grid">
      <div class="metric"><b>RUN STATUS</b><span id="status">IDLE</span></div>
      <div class="metric"><b>STEP</b><span id="step">0</span></div>
    </div>
    <p class="run" id="runId">run_id: -</p>
    <div class="metric"><b>CURRENT</b><span id="current" style="font-size:13px">-</span></div>
    <div style="height:10px"></div>
    <div class="metric"><b>LAST ACTION</b><span id="action" style="font-size:14px">-</span></div>
    <p id="result" class="muted"></p>
  </section>

  <section class="card">
    <b>EVENT LOG</b>
    <div id="events" class="muted" style="margin-top:10px">まだ実行していません。</div>
  </section>
</main>
<script>
const runButton = document.getElementById('runButton');
let timer = null;

function paint(data) {
  document.getElementById('status').textContent = data.status || '-';
  document.getElementById('status').className = data.status === 'COMPLETED' ? 'ok' : (data.status === 'FAILED' ? 'bad' : '');
  document.getElementById('step').textContent = String(data.step_count || 0);
  document.getElementById('runId').textContent = 'run_id: ' + (data.run_id || '-');
  document.getElementById('current').textContent = data.current_url || '-';
  const last = data.last_action;
  document.getElementById('action').textContent = last ? [last.type, last.name || last.url || last.key || ''].filter(Boolean).join(' · ') : '-';
  document.getElementById('result').textContent = data.result || data.error || '';

  const events = Array.isArray(data.events) ? data.events : [];
  document.getElementById('events').innerHTML = events.length ? events.map((e) => {
    const a = e.proposed_action || {};
    return '<div class="event"><strong>STEP ' + e.step + ' · ' + (a.type || '?') + '</strong><div>' +
      (a.name || a.url || a.value || a.result || '') + '</div><div class="muted">' +
      (e.before_url || '') + ' → ' + (e.after_url || '') + '</div></div>';
  }).join('') : 'まだEVENTはありません。';
}

async function poll(runId) {
  try {
    const res = await fetch('/api/run/' + encodeURIComponent(runId));
    const data = await res.json();
    paint(data);
    if (data.status === 'COMPLETED' || data.status === 'FAILED' || data.status === 'CANCELLED') {
      clearInterval(timer);
      timer = null;
      runButton.disabled = false;
    }
  } catch (e) {
    document.getElementById('result').textContent = String(e);
    clearInterval(timer);
    timer = null;
    runButton.disabled = false;
  }
}

runButton.addEventListener('click', async () => {
  runButton.disabled = true;
  document.getElementById('result').textContent = '';
  const goal = document.getElementById('goal').value.trim();
  const res = await fetch('/api/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({goal})
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('result').textContent = data.detail || 'run creation failed';
    runButton.disabled = false;
    return;
  }
  paint(data);
  await poll(data.run_id);
  timer = setInterval(() => poll(data.run_id), 900);
});
</script>
</body>
</html>
"""


class RunRequest(BaseModel):
    goal: str


def snapshot_from_state(state: Any) -> dict[str, Any]:
    events = [asdict(e) for e in state.events]
    last = state.events[-1] if state.events else None
    return {
        "run_id": state.run_id,
        "status": state.status,
        "step_count": state.step_count,
        "goal": state.goal,
        "current_url": last.after_url if last else state.start_url,
        "last_action": last.proposed_action if last else None,
        "result": state.final_result,
        "error": state.error,
        "events": events,
    }


def save_snapshot(run_id: str, payload: dict[str, Any]) -> None:
    with RUNS_LOCK:
        RUNS[run_id] = payload


def run_demo(run_id: str, goal: str) -> None:
    planner = ScriptedPlanner([
        Action(type="click", role="button", name="プロフィール", reason="goal requires profile editor"),
        Action(type="fill", role="textbox", name="表示名", value="ヒデロック", reason="fill target field"),
        Action(type="click", role="button", name="保存", reason="submit form"),
        Action(type="done", result="プロフィールを保存完了", reason="success page observed"),
    ])

    run_dir = RUN_ROOT / run_id
    runner = MiniFishRunner(
        planner,
        max_steps=10,
        max_duration_seconds=60,
        headless=True,
        capture_dir=str(run_dir / "captures"),
        log_path=str(run_dir / "run.json"),
        on_event=lambda state, _event: save_snapshot(run_id, snapshot_from_state(state)),
    )
    state = runner.run(goal=goal, start_url="about:blank", start_html=DEMO_HTML, run_id=run_id)
    save_snapshot(run_id, snapshot_from_state(state))


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return CONTROL_HTML


@app.get("/api/_healthcheck")
async def healthcheck() -> dict[str, Any]:
    return {"ok": True, "service": "MiniFish Cloud v0.1", "mode": "demo-worker"}


@app.post("/api/run")
async def create_run(request: RunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    goal = request.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="GOAL is required")

    run_id = "run_" + uuid.uuid4().hex[:16]
    initial = {
        "run_id": run_id,
        "status": "PENDING",
        "step_count": 0,
        "goal": goal,
        "current_url": "about:blank",
        "last_action": None,
        "result": None,
        "error": None,
        "events": [],
    }
    save_snapshot(run_id, initial)
    background_tasks.add_task(run_demo, run_id, goal)
    return initial


@app.get("/api/run/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    with RUNS_LOCK:
        data = RUNS.get(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="run not found")
    return data
