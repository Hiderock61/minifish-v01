"""Isolated security-contract checks; never uses live VNC, sites or credentials."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "tools/novnc_local_accept.py"
spec = importlib.util.spec_from_file_location("novnc_local_accept", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class LocalAcceptanceSecurityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home"
        self.home.mkdir(mode=0o700)
        (self.home / ".local/share/minifish/g1b-mock-only").mkdir(parents=True)
        self.private = self.home / ".local/share/minifish/g1b-mock-only"
        self.root = self.private.parent
        self.private.chmod(0o700)
        self.root.chmod(0o700)
        self.secret = self.private / "vnc-password.txt"
        self.secret.write_text("AbC345Xz", encoding="ascii")
        self.secret.chmod(0o600)
        for name, val in [("HOME", self.home), ("ROOT", self.root),
                          ("PRIVATE", self.private), ("SECRET", self.secret),
                          ("SNAPSHOT", self.private/"novnc-auth-verified.png")]:
            p = patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {"CODESPACE_NAME": mod.EXPECTED})
        p.start()
        self.addCleanup(p.stop)

    def test_valid_secret_only_inside_test(self):
        self.assertEqual(mod.read_secret(), "AbC345Xz")

    def test_root_mode_mismatch_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(mod.Hold) as ctx: mod.file_guard()
        self.assertEqual(str(ctx.exception), "HOLD_PRIVATE_PATH_UNSAFE")

    def test_subdirectory_symlink_rejected(self):
        self.secret.unlink()
        self.private.rmdir()
        self.private.symlink_to(self.root)
        with self.assertRaises(mod.Hold): mod.file_guard()

    def test_secret_symlink_rejected(self):
        self.secret.unlink()
        self.secret.symlink_to("/etc/hostname")
        with self.assertRaises(mod.Hold): mod.file_guard()

    def test_secret_mode_rejected(self):
        self.secret.chmod(0o644)
        with self.assertRaises(mod.Hold): mod.read_secret()

    def test_secret_length_rejected(self):
        self.secret.write_text("1234567")
        with self.assertRaises(mod.Hold): mod.read_secret()

    def test_secret_encoding_rejected(self):
        self.secret.write_bytes(b"\xff"*8)
        with self.assertRaises(mod.Hold): mod.read_secret()

    def test_secret_characters_rejected(self):
        self.secret.write_text("1234/678")
        with self.assertRaises(mod.Hold): mod.read_secret()

    def test_wrong_codespace_rejected_before_network(self):
        with patch.dict(os.environ, {"CODESPACE_NAME": "glorious-disco-rqvjwqq6gpgcxr6j"}),patch.object(mod, "tcp_ready",side_effect=AssertionError("network")),self.assertRaises(mod.Hold):
            mod.gate()

    def test_fixed_output_does_not_echo_secret(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.emit("GATE_READY", canvas_visible=False)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["secret_disclosed"])
        self.assertEqual(data["owner_post_count"], 0)
        self.assertNotIn("AbC345Xz",buf.getvalue())

    def test_local_only_route(self):
        class R:
            def __init__(self,url):
                self.request=type("Q",(),{"url":url})()
                self.action=None
            def continue_(self): self.action="ALLOW"
            def abort(self): self.action="BLOCK"
        for url, expected in [
            ("http://127.0.0.1:6081/vnc.html", "ALLOW"),
            ("http://127.0.0.1:6081/app/ui.js", "ALLOW"),
            ("http://127.0.0.1:8002/login-ready","BLOCK"),
            ("https://crowdworks.jp/login","BLOCK"),
            ("https://attacker.example/","BLOCK"),
            ("file:///etc/passwd","BLOCK"),
        ]:
            r=R(url)
            mod.local_only(r)
            self.assertEqual(r.action,expected)

    def test_status_does_not_read_secret(self):
        with patch.object(mod,"read_secret",side_effect=AssertionError("read")),patch.object(mod,"tcp_ready",return_value=True),patch.object(mod,"http_ready",return_value=True),contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(mod.main(["--check"]),0)
        self.assertEqual(json.loads(buf.getvalue())["verdict"], "GATE_READY")

    def test_no_snapshot_in_check_mode(self):
        with self.assertRaises(SystemExit):
            mod.main(["--check","--snapshot-private"])


if __name__ == "__main__":
    unittest.main()
