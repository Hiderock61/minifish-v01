from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any, Literal
import os
import uuid
import re
import secrets

from minifish.owner_runtime import diagnose as owner_diagnose, start_owner_desktop

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from minifish import Action, MiniFishRunner, OpenAIPlanner, ScriptedPlanner

app = FastAPI(title="MiniFish Cloud v0.2")

# Process-local, private-portal-only nonce. Never placed in static HTML or logs.
_OWNER_START_NONCE = secrets.token_urlsafe(32)


class OwnerStartProof(BaseModel):
    nonce: str = Field(min_length=40, max_length=128)


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

POIKATSU_DEMO_HTML = r"""
<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>MiniFish ポイ活模擬アンケート</title></head>
<body>
<h1>ポイ活のススメ｜安全な模擬アンケート</h1>
<p>本人回答DBと同じ形式の練習用画面。外部送信・ポイント付与はありません。</p>
<fieldset><legend>Q1. コンビニを利用する頻度</legend>
<label><input type="radio" name="q1" value="weekly8">週8回以上</label>
<label><input type="radio" name="q1" value="weekly1">週1回程度</label>
</fieldset>
<fieldset><legend>Q2. 同じ品質ならどちらを選びますか</legend>
<label><input type="radio" name="q2" value="cheaper">安い方</label>
<label><input type="radio" name="q2" value="expensive">高い方</label>
</fieldset>
<fieldset><legend>Q3. 今見ている広告への印象</legend>
<label><input type="radio" name="q3" value="positive">良い</label>
<label><input type="radio" name="q3" value="negative">悪い</label>
</fieldset>
<p>Q3は実際の広告素材がないため未回答のまま残す。</p>
<p>送信ボタンは設置しない。</p>
</body></html>
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
  <span hidden id="owner-proxy-fix" data-build="G1_OWNER_START_NONCE_20261021"></span>
  <h1>iPhone操縦席 🐟</h1>
  <p class="sub">DemoはAIなし。AgentはURL＋GOALを受け、クラウド側のChromiumをMiniFishが操作する。</p>
  <section class="card" aria-label="クラウドワークスのログイン">
    <b>🔑 クラウドワークスの本人ログイン</b>
    <p class="muted">ここからMiniFishの本人専用ブラウザを開きます。パスワードをChatGPTに貼らないでください。</p>
    <a id="ownerLoginLink" href="#" style="display:block;padding:14px;border-radius:12px;background:#87c3ff;color:#071025;font-weight:850;text-align:center;text-decoration:none">MiniFishでログインする</a>
    <p id="ownerLoginNotice" class="muted">起動状態を自動で確認しています…</p>
    <button id="ownerBoot" type="button" hidden style="background:#ffcf8c;color:#071025;width:100%">MiniFishの画面を起動する</button>
  </section>

  <section class="card">
    <label for="mode">MODE</label>
    <select id="mode">
      <option value="demo">DEMO｜安全な内蔵ページ</option>
      <option value="poikatsu_demo">POIKATSU DEMO｜模擬アンケート</option>
      <option value="public_read">PUBLIC READ｜登録済みサイト（API課金なし）</option>
      <option value="agent">AGENT｜実Web</option>
    </select>
    <label for="sitePicker">公開サイト（PUBLIC READ）</label>
    <select id="sitePicker">
      <option value="https://example.com/">Example Domain｜動作試験</option>
      <option value="https://docs.python.org/3/">Python公式ドキュメント</option>
      <option value="https://github.com/Hiderock61/minifish-v01">MiniFish GitHub</option>
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
const ownerLink = document.getElementById('ownerLoginLink');
const ownerNote = document.getElementById('ownerLoginNotice');
const ownerBoot = document.getElementById('ownerBoot');
const codehost = location.hostname;
const onCodespace = /^[a-z0-9-]+-8000\.app\.github\.dev$/.test(codehost);
const ownerUrl = onCodespace ?
  "https://" + codehost.replace(/-8000\.app\.github\.dev$/, "-8002.app.github.dev") + "/login-ready" : null;

function ownerState(state) {
  const status=state.status || "UNKNOWN";
  const messages={
    READY:"ログイン用の画面と表示装置が応答しています。Privateで開けることを確認してからログインします。",
    OFFLINE:"まだ起動していません。下のボタンで起動できます。",
    STARTING:"いま起動しています。しばらくお待ちください。",
    PARTIAL_NEEDS_INSPECTION:"画面か操作装置の片方が応答しません。ログインせず工務店で修理します。",
    CODESPACE_REQUIRED:"Codespacesのプライベート画面でのみ利用できます。",
    SCRIPT_MISSING:"MiniFishの新しい部品が足りません。",
    PRIVATE_DIRECTORY_UNSAFE:"保存先の安全設定を確認する必要があります。",
    PRIVATE_LOG_UNSAFE:"起動記録の安全設定を確認する必要があります。",
    BOOT_BLOCKED:"起動に失敗しました。再試行できますが、ログインはまだしないでください。",
    DESKTOP_MISSING:"画面共有に必要な部品がありません。再構築の完了状態を調べます。",
    NOVNC_MISSING:"画面共有の表示部品が見つかりません。",
    DESKTOP_IN_USE:"専用画面の番号がほかの装置で使用されています。",
    AUTH_FILE_UNSAFE:"画面の認証情報の保護設定に問題があります。安全のため停止します。",
    AUTH_SETUP_FAILED:"画面の認証設定が完了しませんでした。",
    BOOT_CAUSE_NOT_OBSERVED:"起動記録に故障理由が残っていません。安全のためログイン停止です。",
    BOOT_FAILED_UNCLASSIFIED:"装置側でエラーが出ました。秘密を見せずに原因を調査します。",
    DESKTOP_START_FAILED:"ブラウザ用の画面を起動できませんでした。",
    NOVNC_START_FAILED:"画面共有ソフトの起動に失敗しました。",
    LOCAL_SCREEN_UNAVAILABLE:"画面共有の内部接続がまだできていません。",
    LOGIN_CONTROLLER_FAILED:"ログイン操作装置を起動できませんでした。",
    PRIVATE_OWNER_ACCESS_REJECTED:"この操縦席の本人確認に失敗しました。まだログインしないでください。",
    PRIVATE_OWNER_SERVER_ERROR:"操縦席の自己診断が内部エラーで停止しました。ログインしないでください。",
    PRIVATE_OWNER_CONNECTION_ERROR:"操縦席と自己診断装置が通信できません。ログインしないでください。"
  };
  ownerNote.textContent=messages[status]||"準備が確認できません。ログインはまだしないでください。";
  if(ownerUrl && status==="READY") {
    ownerLink.href=ownerUrl;
    ownerLink.setAttribute("aria-disabled","false");
    ownerLink.style.opacity="1";
    ownerLink.style.pointerEvents="auto";
  } else {
    ownerLink.removeAttribute("href");
    ownerLink.setAttribute("aria-disabled","true");
    ownerLink.style.opacity="0.42";
    ownerLink.style.pointerEvents="none";
  }
  ownerBoot.hidden=!(ownerUrl && state.can_start === true);
}
// The private port serves a fresh one-use-purpose start proof to its own
// authenticated page. It is never shown in the UI or copied to GitHub.
let ownerStartNonce = "";
async function ownerCheck() {
  if(!ownerUrl){ownerState({status:"CODESPACE_REQUIRED"});return;}
  try {
    const response=await fetch("/api/owner/diagnose",{credentials:"same-origin",cache:"no-store"});
    if(response.ok) {
      const state=await response.json();
      ownerStartNonce=typeof state.start_nonce==="string" ? state.start_nonce : "";
      ownerState(state);
    } else {
      ownerStartNonce="";
      ownerState({status:response.status===403?"PRIVATE_OWNER_ACCESS_REJECTED":"PRIVATE_OWNER_SERVER_ERROR"});
    }
  } catch (_) {
    ownerStartNonce="";
    ownerState({status:"PRIVATE_OWNER_CONNECTION_ERROR"});
  }
}
ownerBoot.addEventListener("click",async () => {
  if(!ownerStartNonce) {
    ownerState({status:"PRIVATE_OWNER_ACCESS_REJECTED",can_start:false});
    return;
  }
  ownerBoot.disabled=true;
  ownerState({status:"STARTING",can_start:false});
  try {
    const response=await fetch("/api/owner/start",{
      method:"POST",credentials:"same-origin",cache:"no-store",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({nonce:ownerStartNonce})
    });
    if(!response.ok) ownerState({
      status:response.status===403?"PRIVATE_OWNER_ACCESS_REJECTED":"PRIVATE_OWNER_SERVER_ERROR"
    });
    else ownerState(await response.json());
  } catch (_) {ownerState({status:"PRIVATE_OWNER_CONNECTION_ERROR"});}
  ownerBoot.disabled=false;
});
ownerCheck();
setInterval(ownerCheck,3000);
const runButton = document.getElementById('runButton');
const stopButton = document.getElementById('stopButton');
const modeInput = document.getElementById('mode');
const urlInput = document.getElementById('url');
const sitePicker = document.getElementById('sitePicker');
sitePicker.addEventListener('change', () => {
  if (modeInput.value === 'public_read') urlInput.value = sitePicker.value;
});
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
  const url = mode === 'public_read' ? sitePicker.value : urlInput.value.trim();
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
  if (modeInput.value === 'public_read') {
    urlInput.value = sitePicker.value;
    document.getElementById('goal').value = '登録済み公開ページのタイトルと本文を確認する';
    document.getElementById('notice').textContent =
      '無人公開ページを1回読むだけ。投稿・ログイン・API課金はしません。';
    return;
  }
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
    mode: Literal["demo", "poikatsu_demo", "public_read", "agent"] = "demo"
    human_facts: list[str] = Field(default_factory=list)


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
        "ledger": [asdict(item) for item in state.ledger],
        "human_facts": list(state.human_facts),
    }


def save_snapshot(run_id: str, payload: dict[str, Any]) -> None:
    with RUNS_LOCK:
        RUNS[run_id] = payload


def is_cancelled(run_id: str) -> bool:
    with RUNS_LOCK:
        return CANCEL_FLAGS.get(run_id, False)


def run_worker(run_id: str, request: RunRequest) -> None:
    run_dir = RUN_ROOT / run_id
    if request.mode == "public_read":
        from minifish.readonly_probe import run_public_readonly
        if is_cancelled(run_id):
            return
        result = run_public_readonly(
            job_id=run_id, goal=request.goal, url=request.url or "",
            run_dir=run_dir, run_id=run_id,
            should_stop=lambda: is_cancelled(run_id),
        )
        cancelled = is_cancelled(run_id)
        safe_status = (
            "CANCELLED" if cancelled else
            "COMPLETED" if result["status"] == "PASS" else
            "WAITING" if result["status"] == "BLOCKED" else "FAILED"
        )
        save_snapshot(run_id, {
            "run_id": run_id, "status": safe_status,
            "step_count": result.get("steps", 0), "goal": request.goal,
            "mode": "public_read", "start_url": request.url,
            "current_url": result.get("observed_url") or request.url,
            "last_action": {"type": "done"} if safe_status == "COMPLETED" else None,
            "result": " | ".join(filter(None, [
                str(result.get("status")), str(result.get("title") or ""),
                str(result.get("public_excerpt") or ""), str(result.get("reason") or "")
            ])),
            "error": None if safe_status == "COMPLETED" else str(result.get("reason")),
            "events": [], "ledger": [result.get("evidence_checks", {})],
            "human_facts": list(request.human_facts),
        })
        return
    if request.mode == "demo":
        planner = ScriptedPlanner([
            Action(type="click", role="button", name="プロフィール", reason="goal requires profile editor"),
            Action(type="fill", role="textbox", name="表示名", value="ヒデロック", reason="fill target field"),
            Action(type="click", role="button", name="保存", reason="submit form"),
            Action(type="done", result="プロフィールを保存完了", reason="success page observed"),
        ])
        start_url = "about:blank"
        start_html = DEMO_HTML
    elif request.mode == "poikatsu_demo":
        # Only user-confirmed mock answers. Unknown Q3 stays untouched.
        planner = ScriptedPlanner([
            Action(type="click", role="radio", name="週8回以上", reason="mock Q1: existing answer candidate"),
            Action(type="click", role="radio", name="安い方", reason="mock Q2: existing answer candidate"),
            Action(type="done", result="模擬回答2件を入力、未知のQ3は未回答、外部送信なし。HTMLキャプチャで選択状態を確認する", reason="dry-run only"),
        ])
        start_url = "about:blank"
        start_html = POIKATSU_DEMO_HTML
    else:
        planner = OpenAIPlanner()
        start_url = request.url or ""
        start_html = None

    runner = MiniFishRunner(
        planner,
        max_steps=25,
        max_duration_seconds=180,
        headless=True,
        profile_path=None,  # Never persist live login cookies in legacy plaintext JSON
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
        human_facts=request.human_facts,
    )
    save_snapshot(
        run_id,
        snapshot_from_state(state, mode=request.mode, start_url=start_url),
    )


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return CONTROL_HTML


@app.get("/api/_maintenance_state")
async def maintenance_state() -> dict[str, bool]:
    """Only return whether in-memory jobs are idle, never customer data."""
    with RUNS_LOCK:
        active=any(run.get("status") in ("PENDING","RUNNING","WAITING")
                   for run in RUNS.values())
    return {"idle":not active}


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
    if request.mode == "public_read":
        from minifish.command_tower import MiniFishCommandTower
        dec = MiniFishCommandTower.preflight_public_readonly(
            "browser_ui", goal, request.url or ""
        )
        if dec.state != "PASS":
            raise HTTPException(status_code=400, detail=dec.reason)
    if request.mode == "agent":
        if not request.url or not request.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="AGENT mode requires an http(s) START URL")
        if not (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")):
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY and OPENAI_MODEL are required for AGENT mode")

    start_url = "about:blank" if request.mode in ("demo", "poikatsu_demo") else (request.url or "")
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
        "ledger": [],
        "human_facts": list(request.human_facts),
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


def _private_owner_request(
    request: Request, *, state_change: bool = False, proof: str = ""
) -> None:
    """Codespaces PRIVATE port; CSRF nonce survives GitHub proxy Host rewrites.

    The read-only endpoint is reachable only through an authenticated
    private Codespaces forward. The random process-local nonce is returned
    to that SAME origin via JSON (never static HTML or a GitHub Issue).
    Writing requires the nonce in an application/json POST. Unlike Host
    / Origin equality, the nonce is not sensitive to proxy header rewrites.
    If an Origin or Sec-Fetch-Site *is* supplied, reject any contradictory
    cross-origin request. Browser CORS remains disabled.
    """
    name = os.getenv("CODESPACE_NAME", "")
    if not name or not re.fullmatch(r"[a-z0-9-]+", name):
        raise HTTPException(403, "PRIVATE_CODESPACE_REQUIRED")
    if not state_change:
        return
    if not secrets.compare_digest(proof, _OWNER_START_NONCE):
        raise HTTPException(403, "OWNER_START_PROOF_REQUIRED")
    origin = request.headers.get("origin", "")
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site not in ("", "same-origin"):
        raise HTTPException(403, "OWNER_CROSS_SITE_REJECTED")
    if origin:
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        host = (parsed.hostname or "").lower()
        if not (
            parsed.scheme == "https"
            and bool(re.fullmatch(r"[a-z0-9-]+-8000\.app\.github\.dev", host))
            and parsed.port is None
            and not parsed.username and not parsed.password
            and origin == "https://" + host
        ):
            raise HTTPException(403, "OWNER_CROSS_ORIGIN_REJECTED")

@app.get("/api/owner/diagnose")
def owner_runtime_status(request: Request):
    _private_owner_request(request)
    return JSONResponse(
        {**owner_diagnose(), "start_nonce": _OWNER_START_NONCE},
        headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer"},
    )


@app.post("/api/owner/start")
def owner_runtime_start(request: Request, proof: OwnerStartProof):
    _private_owner_request(request, state_change=True, proof=proof.nonce)
    return JSONResponse(start_owner_desktop(), headers={"Cache-Control":"no-store"})
