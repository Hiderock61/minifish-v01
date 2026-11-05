"""Replace only an idle local owner controller with a diagnostic launcher."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

root = Path("/workspaces/minifish-v01")
assert os.getenv("CODESPACE_NAME") == "accursed-apparition-6q7jwqq5965h4rpq"
with urlopen("http://127.0.0.1:8002/g1/owner/status", timeout=3) as reply:
    state = json.load(reply)
assert not state["busy"]
source = (root / "start_g1b_mock.sh").read_text()
assert source.count("uvicorn g1b_mock_app:app") == 1
probe = Path(sys.argv[1]).resolve()
launcher = probe.parent / "start_g1b_mock.sh"
launcher.write_text(source.rsplit("uvicorn g1b_mock_app:app", 1)[0]
                    + sys.executable + " -B " + str(probe) + chr(10))
pids = []
for path in Path("/proc").iterdir():
    if not path.name.isdigit():
        continue
    try:
        args = (path / "cmdline").read_bytes().split(bytes([0]))
        original = b"g1b_mock_app:app" in args and b"8002" in args
        diagnostic = str(probe).encode() in args
        if path.stat().st_uid == os.geteuid() and (original or diagnostic) and int(path.name) != os.getpid():
            pids.append(int(path.name))
    except OSError:
        pass
assert len(pids) == 1
os.kill(pids[0], signal.SIGTERM)
for attempt in range(100):
    try:
        with socket.create_connection(("127.0.0.1", 5911), timeout=0.1):
            pass
    except OSError:
        break
    time.sleep(0.2)
else:
    raise SystemExit("HOLD_OLD_RUNTIME_CLEANUP")
subprocess.Popen(["bash", str(launcher)], cwd=root,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 start_new_session=True)
print("UI_PROBE_RUNTIME_START_REQUESTED")
