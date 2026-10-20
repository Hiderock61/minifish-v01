"""MiniFish: existing Codespace fetches only PR #33 with six successful checks."""
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com/repos/Hiderock61/minifish-v01"
WORKFLOWS = frozenset((
    "MiniFish tests",
    "MiniFish Chat-to-ReadOnly Bridge v0.1",
    "MiniFish G1b private GUI mock login acceptance",
    "MiniFish G1 encrypted mock session acceptance",
    "MiniFish G1 pre-login and no-auth typing (zero AI)",
    "MiniFish real public input readback (no login, no submission)",
))

class Hold(Exception):
    pass

def api(path):
    try:
        req = Request(API + path, headers={"User-Agent":"MiniFish-Codespace-Updater",
                                         "Accept":"application/vnd.github+json"})
        with urlopen(req, timeout=8) as res:
            data = res.read(300001)
        if len(data)>300000:
            raise Hold("API_TOO_LARGE")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise Hold("API_BAD_DATA")
        return result
    except (OSError, ValueError):
        raise Hold("API_UNAVAILABLE") from None

def git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                           text=True, timeout=35)
    except (OSError, subprocess.TimeoutExpired):
        raise Hold("GIT_UNAVAILABLE") from None
    if r.returncode:
        raise Hold("GIT_FAILED")
    return r.stdout.strip()

def listening(port):
    try:
        with socket.create_connection(("127.0.0.1",port),timeout=.25):
            return True
    except OSError:
        return False

def local(port,path):
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}",timeout=1) as res:
            if res.status!=200:
                raise Hold("LOCAL_UNREADABLE")
            return json.loads(res.read(8192))
    except (OSError, ValueError):
        raise Hold("LOCAL_UNREADABLE") from None

def safe():
    if not os.getenv("CODESPACE_NAME"):
        raise Hold("NOT_CODESPACE")
    remote=git("remote","get-url","origin").rstrip("/")
    if not re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"Hiderock61/minifish-v01(?:\.git)?", remote, re.I):
        raise Hold("OTHER_REMOTE")
    if git("symbolic-ref","--short","HEAD")!="minifish-login-33":
        raise Hold("OTHER_BRANCH")
    if git("status","--porcelain","--untracked-files=no"):
        raise Hold("DIRTY_WORKTREE")
    try:
        cfg=json.loads((ROOT/".devcontainer/devcontainer.json").read_text())
        if any(cfg["portsAttributes"][str(p)]["visibility"]!="private"
               for p in (8000,8002,6081)):
            raise Hold("PORTS_NOT_PRIVATE")
    except (OSError, KeyError, ValueError, TypeError):
        raise Hold("PORTS_UNKNOWN")
    if listening(8000) and local(8000,"/api/_maintenance_state").get("idle") is not True:
        raise Hold("RUN_ACTIVE_OR_UNKNOWN")
    if listening(8002):
        if local(8002,"/g1/owner/status").get("busy") is not False:
            raise Hold("LOGIN_ACTIVE_OR_UNKNOWN")
    elif listening(6081) or listening(5911):
        raise Hold("DESKTOP_PARTIAL")

def verified_head():
    pr=api("/pulls/33")
    head=pr.get("head") or {}
    if (pr.get("state")!="open" or
        head.get("ref")!="codex/minifish-g1-mock-encrypted-session-20261016" or
        (head.get("repo") or {}).get("full_name")!="Hiderock61/minifish-v01"):
        raise Hold("PR_IDENTITY_CHANGED")
    sha=head.get("sha")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
        raise Hold("PR_SHA_INVALID")
    data=api(f"/actions/runs?head_sha={sha}&event=pull_request&per_page=100")
    runs=data.get("workflow_runs")
    if not isinstance(runs,list):
        raise Hold("CI_UNAVAILABLE")
    latest={}
    for run in runs:
        if not isinstance(run,dict) or run.get("head_sha")!=sha:
            continue
        name=run.get("name")
        if name in WORKFLOWS and name not in latest:
            latest[name]=(run.get("status"),run.get("conclusion"))
    if any(latest.get(name)!=("completed","success") for name in WORKFLOWS):
        raise Hold("CI_NOT_GREEN")
    return sha

def refresh():
    try:
        r=subprocess.run([sys.executable,"tools/refresh_codespace_ui.py"],
                         cwd=ROOT,capture_output=True,text=True,timeout=100)
    except (OSError,subprocess.TimeoutExpired):
        raise Hold("REFRESH_FAILED") from None
    if r.returncode or "MINIFISH_LOGIN_UPDATE=READY_LOGIN_" not in r.stdout:
        raise Hold("REFRESH_NOT_READY")

def once():
    safe()
    sha=verified_head()
    current=git("rev-parse","HEAD")
    if current!=sha:
        git("fetch","--no-tags","origin","pull/33/head")
        if git("rev-parse","FETCH_HEAD")!=sha:
            raise Hold("PR_CHANGED_DURING_FETCH")
        safe()
        r=subprocess.run(["git","merge-base","--is-ancestor","HEAD","FETCH_HEAD"],
                         cwd=ROOT,capture_output=True,timeout=8)
        if r.returncode:
            raise Hold("NOT_FAST_FORWARD")
        git("merge","--ff-only","FETCH_HEAD")
    safe()
    refresh()
    return "READY_CURRENT" if current==sha else "READY_UPDATED"

def main():
    watch="--watch" in sys.argv[1:]
    while True:
        try:
            print("MINIFISH_AUTO_UPDATE="+once(),flush=True)
        except Hold as e:
            print("MINIFISH_AUTO_UPDATE=HOLD_"+str(e),flush=True)
        except Exception:
            print("MINIFISH_AUTO_UPDATE=HOLD_UNKNOWN",flush=True)
        if not watch:
            return
        time.sleep(300)

if __name__=="__main__":
    main()
