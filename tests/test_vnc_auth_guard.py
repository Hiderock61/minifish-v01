"""Remote login screen security regressions: no real credentials or network."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_remote_login_scripts_parse():
    for name in ("start_auth_desktop.sh", "iphone_login_demo.sh"):
        result = subprocess.run(["bash", "-n", str(ROOT / name)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_remote_login_requires_codespaces_by_default():
    env = dict(os.environ)
    env.pop("CODESPACES", None)
    env.pop("CODESPACE_NAME", None)
    env.pop("MINIFISH_LOCAL_TEST", None)
    result = subprocess.run(
        ["bash", str(ROOT / "start_auth_desktop.sh")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 2
    assert "BLOCKED: remote login desktop requires GitHub Codespaces." in result.stdout


def test_vnc_has_independent_one_time_password_and_private_storage():
    script = (ROOT / "start_auth_desktop.sh").read_text(encoding="utf-8")
    demo = (ROOT / "iphone_login_demo.sh").read_text(encoding="utf-8")
    assert "secrets.token_hex(4)" in script
    assert "x11vnc -storepasswd" in script
    assert "-rfbauth" in script
    assert " -nopw" not in script
    assert "umask 077" in script
    assert 'chmod 600 "$PASSWORD_FILE"' in script
    assert 'rm -f -- "$PASSWORD_FILE" "$AUTH_FILE"' in script
    assert 'MINIFISH_VNC_PASSWORD_PRINT=0 bash start_auth_desktop.sh' in demo
    assert 'cat .minifish/runtime/vnc-password.txt' in demo
