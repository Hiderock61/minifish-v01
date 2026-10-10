from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any, Literal
import os
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from minifish import Action, MiniFishRunner, OpenAIPlanner, ScriptedPlanner

app = FastAPI(title="MiniFish Cloud v0.2")

RUNS: dict[str, dict[str, Any]] = {}
CANCEL_FLAGS: dict[str, bool] = {}
RUNS_LOCK = Lock()
RUN_ROOT = Path(os.getenv("MINIFISH_RUN_ROOT", "/tmp/minifish-runs"))
PROFILE_PATH = os.getenv("MINIFISH_PROFILE_PATH", ".minifish/profile.json")

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
  <title>MiniFish Cloud v0.2</title>
  <style>
    :root { color-scheme:dark; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    * { box-sizing:border-box; }
    body { margin:0; background:#0b1020; color:#eef3ff; }
    main { max-width:720px; margin:0 auto; padding:calc(20px + env(safe-area-inset-top)) 16px 44px; }
    .eyebrow { color:#8ba6ff; font-size:12px; font-weight:800; letter-spacing:.13em; }
    h1 { font-size:32px; margin:8px 0 6px; }
    .sub { color:#aab6d3; line-height:1.5; }
    .card { background:#141c31; border:1px solid #263454; border-radius:18px; padding:15px; margin:14px 0; }
    label { display:block; font-size:12px; color:#9fb0d3; margin:10px 0 6px; font-weight:800; }
    input, textarea, select { width:100%; border-radius:12px; border:1px solid #34476f; background:#0f172a; color:#f8fbff; padding:12px; font-size:16px; }
    textarea { min-height:90px; resize:vertical; }
    .buttons { display:grid; grid-template-columns:1fr 92px; gap:10px; margin-top:12px; }
    button { border:0; border-radius:13px; padding:14px 12px; font-size:16px; font-weight:850; }
    #runButton { background:#7ea1ff; color:#071025; }
    #stopButton { background:#3a2030; color:#ffb4c4; border:1px solid #714052; }
    button:disabled { opacity:.45; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .metric { background:#0f172a; border-radius:12px; padding:12px; overflow-wrap:anywhere; }
    .metric b { display:block; font-size:11px; color:#8ea0c5; margin-bottom:6px; }
    .metric span { font-size:16px; font-weight:850; }
    .ok { color:#78e6a0; } .bad { color:#ff8e8e; } .live { color:#f6d365; }
    .run { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; color:#9aabd0; overflow-wrap:anywhere; }
    .event { border-top:1px solid #263454; padding:11px 0; }
    .event:first-child { border-top:0; }
    .event strong { display:block; margin-bottom:4px; }
    .muted { color:#91a0bf; font-size:12px; overflow-wrap:anywhere; }
    .warn { color:#ffc97f; font-size:12px; line-height:1.45; }
  </style>
</head>
<body>
<main>
  <div class="eyebrow">MINIFISH CLOUD v0.2</div>
  <h1>iPhone操縦席 🐟</h1>
  <p class="sub">DemoはAIなし。AgentはURL＋GOALを受け、クラウド側のChromiumをMiniFishが操作する。</p>

  <section class="card">
    <label for="mode">MODE</label>
    <select id="mode">
      <option value="demo">DEMO｜安全な内蔵ページ</option>
      <option value="agent">AGENT｜実Web</option>
    </select>
    <label for="url">START URL</label>
    <input id="url" type="url" inputmode="url" placeholder="https://example.com">
    <label for="goal">GOAL</label>
    <textarea id="goal">プロフィール編集画面を開き、表示名をヒデロックにして保存する</textarea>
    <div class="buttons">
      <button id="runButton">MiniFishを動かす</button>
      <button id="stopButton" disabled>STOP</button>
    </div>
    <p id="notice" class="warn"></p>
  </section>

  <section class="card">
    <div class="grid">
      <div class="metric"><b>RUN STATUS</b><span id="status">IDLE</span></div>
      <div class="metric"><b>STEP</b><span id="step">0</span></div>
    </div>
    <p class="run" id="runId">run_id: -</p>
    <div class="metric"><b>CURRENT</b><span id="current">-</span></div>
    <div style="height:10px"></div>
    <div class="metric"><b>LAST ACTION</b><span id="action">-</span></div>
    <p id="result" class="muted"></p>
  </section>

  <section class="card">
    <b>EVENT LOG</b>
    <div id="events" class="muted" style="margin-top:10px">まだ実行していません。</div>
  </section>
</main>
<script>
const runButton = document.getElementById('runButton');
const stopButton = document.getElementById('stopButton');
const modeInput = document.getElementById('mode');
const urlInput = document.getElementById('url');
let timer = null;
let currentRunId = null;

function terminal(status) {
  return ['WAITING','COMPLETED','FAILED','CANCELLED'].includes(status);
}

function paint(data) {
  currentRunId = data.run_id || currentRunId;
  const status = data.status || '-';
  const s = document.getElementById('status');
  s.textContent = status;
  s.className = status === 'COMPLETED' ? 'ok' : (status === 'WAITING' ? 'live' : (terminal(status) ? 'bad' : 'live'));
  document.getElementById('step').textContent = String(data.step_count || 0);
  document.getElementById('runId').textContent = 'run_id: ' + (data.run_id || '-');
  document.getElementById('current').textContent = data.current_url || '-';
  const last = data.last_action;
  document.getElementById('action').textContent = last ? [last.type, last.name || last.url || last.key || ''].filter(Boolean).join(' · ') : '-';
  document.getElementById('result').textContent = data.result || data.error || '';
  runButton.disabled = !terminal(status) && status !== '-';
  stopButton.disabled = terminal(status) || status === '-';

  const root = document.getElementById('events');
  root.replaceChildren();
  const events = Array.isArray(data.events) ? data.events : [];
  if (!events.length) {
    root.textContent = 'まだEVENTはありません。';
    return;
  }
  events.forEach((e) => {
    const box = document.createElement('div');
    box.className = 'event';
    const strong = document.createElement('strong');
    const a = e.proposed_action || {};
    strong.textContent = 'STEP ' + e.step + ' · ' + (a.type || '?');
    const detail = document.createElement('div');
    detail.textContent = a.name || a.url || a.value || a.result || '';
    const route = document.createElement('div');
    route.className = 'muted';
    route.textContent = (e.before_url || '') + ' → ' + (e.after_url || '');
    box.append(strong, detail, route);
    root.appendChild(box);
  });
}

async function poll(runId) {
  try {
    const res = await fetch('/api/run/' + encodeURIComponent(runId));
    const data = await res.json();
    paint(data);
    if (terminal(data.status)) {
      clearInterval(timer);
      timer = null;
    }
  } catch (e) {
    document.getElementById('result').textContent = String(e);
    clearInterval(timer);
    timer = null;
    runButton.disabled = false;
  }
}

runButton.addEventListener('click', async () => {
  document.getElementById('notice').textContent = '';
  document.getElementById('result').textContent = '';
  const mode = modeInput.value;
  const goal = document.getElementById('goal').value.trim();
  const url = urlInput.value.trim();
  if (!goal) {
    document.getElementById('notice').textContent = 'GOALが必要です。';
    return;
  }
  if (mode === 'agent' && !url) {
    document.getElementById('notice').textContent = 'AGENTモードはSTART URLが必要です。';
    return;
  }
  runButton.disabled = true;
  const res = await fetch('/api/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({goal, url: url || null, mode})
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('notice').textContent = data.detail || 'run creation failed';
    runButton.disabled = false;
    return;
  }
  paint(data);
  await poll(data.run_id);
  if (!terminal(data.status)) timer = setInterval(() => poll(data.run_id), 900);
});

stopButton.addEventListener('click', async () => {
  if (!currentRunId) return;
  stopButton.disabled = true;
  const res = await fetch('/api/run/' + encodeURIComponent(currentRunId) + '/cancel', {method:'POST'});
  const data = await res.json();
  paint(data);
});

modeInput.addEventListener('change', async () => {
  if (modeInput.value !== 'agent') {
    document.getElementById('notice').textContent = '';
    return;
  }
  try {
    const r = await fetch('/api/_healthcheck');
    const h = await r.json();
    if (!h.openai_ready) document.getElementById('notice').textContent = 'AGENTモードにはサーバー側のOPENAI_API_KEYとOPENAI_MODELが必要です。';
  } catch (_) {}
});
</script>
</body>
</html>
"""


class RunRequest(BaseModel):
    goal: str
    url: str | None = None
    mode: Literal["demo", "agent"] = "demo"


def snapshot_from_state(state: Any, *, mode: str, start_url: str) -> dict[str, Any]:
    events = [asdict(e) for e in state.events]
    last = state.events[-1] if state.events else None
    return {
        "run_id": state.run_id,
        "status": state.status,
        "step_count": state.step_count,
        "goal": state.goal,
        "mode": mode,
        "start_url": start_url,
        "current_url": last.after_url if last else start_url,
        "last_action": last.proposed_action if last else None,
        "result": state.final_result,
        "error": state.error,
        "events": events,
    }


def save_snapshot(run_id: str, payload: dict[str, Any]) -> None:
    with RUNS_LOCK:
        RUNS[run_id] = payload


def is_cancelled(run_id: str) -> bool:
    with RUNS_LOCK:
        return CANCEL_FLAGS.get(run_id, False)


def run_worker(run_id: str, request: RunRequest) -> None:
    run_dir = RUN_ROOT / run_id
    if request.mode == "demo":
        planner = ScriptedPlanner([
            Action(type="click", role="button", name="プロフィール", reason="goal requires profile editor"),
            Action(type="fill", role="textbox", name="表示名", value="ヒデロック", reason="fill target field"),
            Action(type="click", role="button", name="保存", reason="submit form"),
            Action(type="done", result="プロフィールを保存完了", reason="success page observed"),
        ])
        start_url = "about:blank"
        start_html = DEMO_HTML
    else:
        planner = OpenAIPlanner()
        start_url = request.url or ""
        start_html = None

    runner = MiniFishRunner(
        planner,
        max_steps=25,
        max_duration_seconds=180,
        headless=True,
        profile_path=PROFILE_PATH,
        capture_dir=str(run_dir / "captures"),
        log_path=str(run_dir / "run.json"),
        on_event=lambda state, _event: save_snapshot(
            run_id,
            snapshot_from_state(state, mode=request.mode, start_url=start_url),
        ),
        should_stop=lambda: is_cancelled(run_id),
    )
    state = runner.run(
        goal=request.goal,
        start_url=start_url,
        start_html=start_html,
        run_id=run_id,
    )
    save_snapshot(
        run_id,
        snapshot_from_state(state, mode=request.mode, start_url=start_url),
    )


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return CONTROL_HTML


@app.get("/api/_healthcheck")
async def healthcheck() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "MiniFish Cloud v0.2",
        "openai_ready": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")),
        "profile_path": PROFILE_PATH,
    }


@app.post("/api/run")
async def create_run(request: RunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    goal = request.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="GOAL is required")
    if request.mode == "agent":
        if not request.url or not request.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="AGENT mode requires an http(s) START URL")
        if not (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")):
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY and OPENAI_MODEL are required for AGENT mode")

    start_url = "about:blank" if request.mode == "demo" else (request.url or "")
    with RUNS_LOCK:
        for existing in RUNS.values():
            if (
                existing.get("status") in ("PENDING", "RUNNING", "WAITING")
                and existing.get("goal") == goal
                and existing.get("mode") == request.mode
                and existing.get("start_url") == start_url
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"duplicate active run blocked: {existing.get('run_id')} ({existing.get('status')})",
                )

    run_id = "run_" + uuid.uuid4().hex[:16]
    initial = {
        "run_id": run_id,
        "status": "PENDING",
        "step_count": 0,
        "goal": goal,
        "mode": request.mode,
        "start_url": start_url,
        "current_url": start_url,
        "last_action": None,
        "result": None,
        "error": None,
        "events": [],
    }
    with RUNS_LOCK:
        RUNS[run_id] = initial
        CANCEL_FLAGS[run_id] = False
    background_tasks.add_task(run_worker, run_id, request)
    return initial


@app.get("/api/run/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    with RUNS_LOCK:
        data = RUNS.get(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="run not found")
    return data


@app.post("/api/run/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    with RUNS_LOCK:
        data = RUNS.get(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="run not found")
        CANCEL_FLAGS[run_id] = True
        if data["status"] in ("PENDING", "WAITING"):
            data = {**data, "status": "CANCELLED", "result": "cancelled by user"}
            RUNS[run_id] = data
    return data
