"""MiniFish G1b mock-only private visual login gateway.

This *cannot* visit third-party websites: Playwright requests are blocked
unless they target its local synthetic login page. No real credentials, AI,
tokens, real-site sessions, telemetry, or external writes.
"""
from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from minifish.browser import PlaywrightBrowser
from minifish.session_vault import EncryptedSessionVault
from minifish.crowdworks_handoff import handoff as real_handoff

app = FastAPI(title="MiniFish G1b Mock Login (NO REAL ACCOUNTS)", docs_url=None, redoc_url=None)
HOST = "127.0.0.1"
PORT = 8002
BASE = f"http://{HOST}:{PORT}"
AUTH_COOKIE = "g1b_dummy"
AUTH_VALUE = "NOT_A_REAL_ACCOUNT"
MAX_SECONDS = 300

HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MiniFish G1b 模擬ログイン</title>
<style>
body{margin:0;background:#101a2a;color:#f4f7fc;font:16px system-ui,sans-serif}
main{max-width:560px;margin:auto;padding:24px 18px}
h1{font-size:27px}p{line-height:1.6;color:#b9c9e5}
button,a.gui{display:block;box-sizing:border-box;width:100%;margin:12px 0;
padding:15px;border-radius:12px;background:#87c3ff;color:#0b2036;
border:0;text-align:center;text-decoration:none;font-weight:700;font-size:16px}
button:disabled{opacity:.5}#result{background:#1d2d46;padding:16px;border-radius:12px}
</style></head><body><main>
<h1>🐟 MiniFish｜G1b 模擬ログイン</h1>
<p>架空のログインだけを練習。実際のランサーズやココナラには接続しません。
GitHub Codespaces の 8002 / 6081 ポートは必ず Private にしてください。</p>
<div id="result">状態を確認しています…</div>
<button id="start">① 架空ログイン画面を起動</button>
<button id="showPass">② この環境のVNCパスワードを表示</button>
<p id="passInfo">パスワードは画面を開いた本人だけが確認できます。</p>
<a class="gui" id="desktop" href="#" target="_blank" rel="noopener">③ ブラウザの画面を開く（6081）</a>
<button id="mockClick">④ 架空のログインボタンを押す（模擬操作）</button>
<button id="save">⑤ 暗号化して保存</button>
<button id="verify">⑥ ブラウザ再起動で復元を確認</button>
<p><a class="gui" href="/login-ready">実サイト・クラウドワークスのログイン準備へ</a></p>
<p>この模擬画面には本物のID・パスワードを入力しないでください。
保存したものはCodespaces内部の架空セッションだけです。</p>
<script>
const host=location.hostname;
const valid=/^[a-z0-9-]+-8002\.app\.github\.dev$/.test(host);
const desktop=document.getElementById("desktop");
if(valid)desktop.href="https://"+host.replace(/-8002\.app\.github\.dev$/,"-6081.app.github.dev")+"/vnc.html";
else if(host==="127.0.0.1"||host==="localhost")
desktop.href="http://"+host+":6081/vnc.html";
else {desktop.removeAttribute("href");desktop.textContent="Private Codespaces 6081ポートを開く";}
async function status(){
const r=await fetch("/g1b/status",{credentials:"same-origin"});
const d=await r.json();
document.getElementById("result").textContent="STATE: "+d.status+" / "+d.note;
document.getElementById("start").disabled=d.busy;
document.getElementById("save").disabled=!d.busy;
document.getElementById("mockClick").disabled=!d.busy;
document.getElementById("verify").disabled=d.busy;
}
async function action(name){
const r=await fetch("/g1b/"+name,{
method:"POST",credentials:"same-origin",headers:{"X-MiniFish-Mock-Action":"G1B"}});
if(!r.ok)document.getElementById("result").textContent="BLOCKED: "+r.status;
await status();
}
document.getElementById("showPass").onclick=async ()=>{
  const r=await fetch("/g1b/vnc-password",{
    method:"POST",credentials:"same-origin",
    headers:{"X-MiniFish-Mock-Action":"G1B"},cache:"no-store"});
  const d=await r.json();
  document.getElementById("passInfo").textContent=
    r.ok?"Private VNC password: "+d.password:"BLOCKED: "+r.status;
};
document.getElementById("mockClick").onclick=()=>action("mock-click");
for(const name of ["start","save","verify"])
document.getElementById(name).onclick=()=>action(name);
status();setInterval(status,1600);
</script></main></body></html>"""


def private_root() -> Path:
    root = Path.home() / ".local" / "share" / "minifish" / "g1b-mock-only"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError("G1B_PRIVATE_DIRECTORY_UNSAFE")
    return root


def mock_vault() -> EncryptedSessionVault:
    root = private_root()
    key_path = root / "mock_only.key"
    if key_path.is_symlink():
        raise ValueError("G1B_KEY_SYMLINK_BLOCKED")
    try:
        fd = os.open(key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(key_path, flags, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass
        fd = os.open(key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    info = os.fstat(fd)
    try:
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("G1B_KEY_PERMISSIONS_UNSAFE")
        with os.fdopen(fd, "rb") as file:
            fd = -1
            key = file.read(64)
    finally:
        if fd >= 0:
            os.close(fd)
    return EncryptedSessionVault(root / "mock_only.vault", key)


def local_only_request(route) -> None:
    url = urlsplit(route.request.url)
    if url.scheme == "http" and url.hostname == HOST and url.port == PORT:
        route.continue_()
    else:
        route.abort()


class MockManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._finish = Event()
        self._mock_click = Event()
        self._worker: Thread | None = None
        self._status = "IDLE"
        self._note = "NO_REAL_ACCOUNT"

    def snapshot(self) -> dict:
        with self._lock:
            active = self._worker is not None and self._worker.is_alive()
            return {"status": self._status, "note": self._note, "busy": active}

    def launch(self, *, verify: bool = False) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ValueError("G1B_ALREADY_RUNNING")
            self._finish = Event()
            self._mock_click = Event()
            self._status = "OPENING"
            self._note = "MOCK_ONLY"
            self._worker = Thread(target=self._run, args=(verify, self._finish), daemon=True)
            self._worker.start()

    def mock_click(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive() or self._status != "WAITING_USER":
                raise ValueError("G1B_NOT_READY")
            self._mock_click.set()

    def finish(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                raise ValueError("G1B_NOT_RUNNING")
            self._finish.set()

    def _set(self, status: str, note: str) -> None:
        with self._lock:
            self._status = status
            self._note = note

    def _run(self, verify: bool, finish: Event) -> None:
        stage = "VAULT"
        try:
            vault = mock_vault()
            if verify and vault.load() is None:
                self._set("BLOCKED", "NO_MOCK_SESSION")
                return
            stage = "BROWSER"
            with PlaywrightBrowser(headless=False, session_vault=vault) as browser:
                stage = "ROUTE"
                assert browser.context is not None
                browser.context.route("**/*", local_only_request)
                stage = "NAVIGATE"
                browser.goto(BASE + ("/mock/private" if verify else "/mock/login"))
                stage = "OBSERVE"
                if verify:
                    valid = "AUTHORIZED_TEST_ONLY" in browser.observe().text_excerpt
                    self._set("RESTORED_PASS" if valid else "BLOCKED",
                              "MOCK_SESSION_RESTORED" if valid else "MOCK_LOGIN_REQUIRED")
                    return
                self._set("WAITING_USER", "OPEN_NO_VNC_AND_CLICK_MOCK_LOGIN")
                stage = "WAITING"
                deadline = time.monotonic() + MAX_SECONDS
                while not finish.wait(0.15):
                    if self._mock_click.is_set():
                        self._mock_click.clear()
                        browser.page.get_by_role("button", name="Mock login").click()
                        self._set("MOCK_CLICKED", "MOCK_LOGIN_ONLY_READY_TO_SAVE")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("G1B_MOCK_LOGIN_TIMED_OUT")
                stage = "FINISH"
                browser.goto(BASE + "/mock/private")
                if "AUTHORIZED_TEST_ONLY" not in browser.observe().text_excerpt:
                    raise ValueError("G1B_MOCK_LOGIN_NOT_VERIFIED")
            self._set("SAVED", "ENCRYPTED_MOCK_SESSION_ONLY")
        except Exception as exc:
            # Fixed public-safe categories. NEVER send cookie, stack or raw URL.
            code = str(exc)
            if code in ("G1B_MOCK_LOGIN_NOT_VERIFIED", "G1B_MOCK_LOGIN_TIMED_OUT",
                        "G1B_PRIVATE_DIRECTORY_UNSAFE", "G1B_KEY_PERMISSIONS_UNSAFE",
                        "G1B_KEY_SYMLINK_BLOCKED", "SESSION_VAULT_DECRYPT_FAILED"):
                self._set("BLOCKED", code)
            else:
                self._set("BLOCKED", "G1B_PRIVATE_SETUP_FAILED_" + stage)


manager = MockManager()


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    local = host in ("127.0.0.1:8002", "localhost:8002")
    codespace = bool(re.fullmatch(r"[a-z0-9-]+-8002\.app\.github\.dev", host))
    expected = ("http://" if local else "https://") + host
    if (request.headers.get("x-minifish-mock-action") != "G1B"
            or not (local or codespace) or origin != expected):
        raise HTTPException(403, "G1B_SAME_ORIGIN_REQUIRED")


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


@app.get("/mock/login", response_class=HTMLResponse)
def login():
    return ('<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<h1>MiniFish MOCK LOGIN ONLY</h1>'
            '<form method="post" action="/mock/auth">'
            '<button type="submit">Mock login</button></form>')


@app.post("/mock/auth")
def mock_auth():
    response = RedirectResponse("/mock/private", status_code=303)
    response.set_cookie(AUTH_COOKIE, AUTH_VALUE, httponly=True, secure=False, samesite="lax")
    return response


@app.get("/mock/private", response_class=HTMLResponse)
def mock_private(request: Request):
    if request.cookies.get(AUTH_COOKIE) != AUTH_VALUE:
        return "<h1>LOGIN_REQUIRED</h1>"
    return "<h1>AUTHORIZED_TEST_ONLY</h1>"


@app.get("/g1b/status")
def status():
    return manager.snapshot()


@app.post("/g1b/start")
def start(request: Request):
    require_same_origin(request)
    try:
        manager.launch()
        return manager.snapshot()
    except ValueError:
        raise HTTPException(409, "G1B_ALREADY_RUNNING") from None


@app.post("/g1b/save")
def save(request: Request):
    require_same_origin(request)
    try:
        manager.finish()
        return manager.snapshot()
    except ValueError:
        raise HTTPException(409, "G1B_NOT_RUNNING") from None


@app.post("/g1b/verify")
def verify(request: Request):
    require_same_origin(request)
    try:
        manager.launch(verify=True)
        return manager.snapshot()
    except ValueError:
        raise HTTPException(409, "G1B_ALREADY_RUNNING") from None


@app.post("/g1b/mock-click")
def mock_click(request: Request):
    require_same_origin(request)
    try:
        manager.mock_click()
        return manager.snapshot()
    except ValueError:
        raise HTTPException(409, "G1B_NOT_READY") from None


@app.post("/g1b/vnc-password")
def vnc_password(request: Request):
    """Show the random mock-only VNC password in the private control page.

    Never log it, include it in a GitHub Issue or commit it to the repository.
    """
    require_same_origin(request)
    if not os.getenv("CODESPACE_NAME"):
        raise HTTPException(403, "G1B_CODESPACE_REQUIRED")
    p = private_root() / "vnc-password.txt"
    try:
        if p.is_symlink():
            raise ValueError("G1B_PASSWORD_SYMLINK_BLOCKED")
        info = p.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("G1B_PASSWORD_PERMISSIONS_UNSAFE")
        value = p.read_text(encoding="ascii")
        if len(value) != 8 or not value.isalnum():
            raise ValueError("G1B_PASSWORD_INVALID")
    except (ValueError, OSError):
        raise HTTPException(503, "G1B_PASSWORD_NOT_READY") from None
    return JSONResponse(
        {"password": value},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


REAL_LOGIN_HTML = r"""<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>🐟 MiniFish｜クラウドワークスのログイン</title>
<style>
body{margin:0;background:#122032;color:#f6faff;font:16px system-ui,sans-serif}
main{max-width:600px;margin:auto;padding:22px 16px}
h1{font-size:24px}p{line-height:1.7}
button,a.gui{display:block;box-sizing:border-box;width:100%;margin:12px 0;
padding:15px;border:0;border-radius:12px;background:#a3ceff;color:#092138;
font-weight:700;font-size:16px;text-align:center;text-decoration:none}
button:disabled{opacity:.5}#status{padding:14px;border-radius:12px;background:#243650}
.note{color:#c3d4ea;font-size:14px}
</style></head><body><main>
<h1>🐟 クラウドワークス｜MiniFishログイン</h1>
<p>MiniFish専用ブラウザを開いて、いつもの方法で本人がログインします。
ChatGPTへパスワードを貼る必要はありません。</p>
<div id="status">接続状態を確認しています…</div>
<button id="open">① MiniFishでログイン画面を開く</button>
<button id="password">② 専用ブラウザの画面パスワードを表示</button>
<p id="passNote" class="note">画面共有のためのパスワードです。クラウドワークスのパスワードではありません。</p>
<a class="gui" id="desktop" target="_blank" rel="noopener noreferrer">③ MiniFishの画面を開く（Private）</a>
<p class="note">画面の中でログインしてください。ログイン操作はMiniFishが自動で行いません。</p>
<button id="finish">④ ログインできたら保存を試す</button>
<button id="reopen">保存した画面を開き直す</button>
<button id="stop">中止する</button>
<p class="note">認証の成功は、保存しただけでは証明できません。
アクセス拒否・別サイトへの移動・追加料金が必要ならそこで停止します。
Codespacesの画面ポートは必ずPrivateにしてください。</p>
<script>
const host=location.hostname;
const codespace=/^[a-z0-9-]+-8002\.app\.github\.dev$/.test(host);
const local=host==="127.0.0.1"||host==="localhost";
const desktop=document.getElementById("desktop");
if(codespace) desktop.href="https://"+host.replace(/-8002\.app\.github\.dev$/,"-6081.app.github.dev")+"/vnc.html";
else if(local) desktop.href="http://"+host+":6081/vnc.html";
else {desktop.removeAttribute("href");desktop.textContent="プライベート画面が見つかりません";}
const headers={"X-MiniFish-Mock-Action":"G1B"};
async function refresh(){
 try{
  const d=await(await fetch("/g1/owner/status",{cache:"no-store",credentials:"same-origin"})).json();
  document.getElementById("status").textContent="現在地："+d.status;
  document.getElementById("open").disabled=d.busy;
  document.getElementById("reopen").disabled=d.busy;
  document.getElementById("finish").disabled=!d.busy;
  document.getElementById("stop").disabled=!d.busy;
 }catch(e){document.getElementById("status").textContent="画面に接続できません";}
}
async function run(name){
 const res=await fetch("/g1/owner/"+name,{method:"POST",headers,
   credentials:"same-origin",cache:"no-store"});
 if(!res.ok) document.getElementById("status").textContent="STOP："+res.status;
 await refresh();
}
for(const name of ["open","finish","reopen","stop"]){
 document.getElementById(name).onclick=()=>run(name);
}
document.getElementById("password").onclick=async()=>{
 const res=await fetch("/g1b/vnc-password",{method:"POST",headers,
   credentials:"same-origin",cache:"no-store"});
 const val=await res.json();
 document.getElementById("passNote").textContent=res.ok?
 "MiniFishの画面用："+val.password+"（ほかには共有しない）":
 "画面の認証情報はまだ準備されていません";
};
refresh();setInterval(refresh,1800);
</script></main></body></html>"""


@app.get("/login-ready", response_class=HTMLResponse)
def live_login_page(request: Request):
    # This is a private Codespaces browser page, not a public login gateway.
    host = request.headers.get("host", "")
    if not (os.getenv("CODESPACE_NAME")
            and re.fullmatch(r"[a-z0-9-]+-8002\.app\.github\.dev", host)):
        raise HTTPException(403, "OWNER_PRIVATE_CODESPACE_ONLY")
    return HTMLResponse(
        REAL_LOGIN_HTML,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@app.get("/g1/owner/status")
def owner_login_status(request: Request):
    if not os.getenv("CODESPACE_NAME"):
        raise HTTPException(403, "OWNER_PRIVATE_CODESPACE_ONLY")
    return JSONResponse(real_handoff.status(), headers={"Cache-Control": "no-store"})


@app.post("/g1/owner/{command}")
def owner_login_action(command: str, request: Request):
    require_same_origin(request)
    if command not in ("open", "finish", "reopen", "stop"):
        raise HTTPException(404, "UNKNOWN_OWNER_COMMAND")
    try:
        if command == "open":
            real_handoff.launch()
        elif command == "reopen":
            real_handoff.launch(check_saved=True)
        elif command == "finish":
            real_handoff.finish()
        else:
            real_handoff.cancel()
    except ValueError:
        raise HTTPException(409, "OWNER_LOGIN_NOT_READY") from None
    return JSONResponse(real_handoff.status(), headers={"Cache-Control": "no-store"})
