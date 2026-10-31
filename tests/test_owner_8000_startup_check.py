"""Pure/mocked tests: no Codespace, no network, no Runtime POST."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "owner_8000_startup_check.py"
spec = importlib.util.spec_from_file_location("owner_8000_startup_check", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class StartupCheckTests(unittest.TestCase):
    def test_only_get_paths(self):
        with self.assertRaises(ValueError):
            mod.get_local("/api/owner/start")

    def test_verdict_recovered(self):
        s = [{"root":{"http":200},"diagnose":{"http":200},"tcp8000_listening":True,"processes":{"uvicorn_cloud_api":1}}]
        self.assertEqual(mod.verdict(s, {}), "HTTP_8000_RECOVERED_OR_AVAILABLE")

    def test_verdict_absent(self):
        s = [{"root":{"http":None},"diagnose":{"http":None},"tcp8000_listening":False,"processes":{"uvicorn_cloud_api":0}}]
        self.assertEqual(mod.verdict(s, {}), "UVICORN_ABSENT_NO_LISTENER")

    def test_verdict_listening(self):
        s = [{"root":{"http":None},"diagnose":{"http":None},"tcp8000_listening":True,"processes":{"uvicorn_cloud_api":1}}]
        self.assertEqual(mod.verdict(s, {}), "PORT_LISTENING_BUT_NO_HTTP_RESPONSE")

    def test_wrong_codespace_no_request(self):
        with patch.dict(mod.os.environ, {"CODESPACE_NAME":"not-the-target"}), patch.object(mod,"get_local",side_effect=AssertionError("Do not call HTTP")),contextlib.redirect_stdout(io.StringIO()) as b:
            ret=mod.run(1,0)
        self.assertEqual(ret,2)
        self.assertIn("HOLD_WRONG_TARGET_OR_DIRECTORY",b.getvalue())

    def test_log_does_not_emit_secrets(self):
        with patch.object(mod.API_LOG.__class__,"stat") as st, patch.object(mod.API_LOG.__class__,"is_symlink",return_value=False),patch.object(mod.API_LOG.__class__,"open") as op:
            st.return_value.st_mode=0o100600
            st.return_value.st_uid=mod.os.geteuid()
            st.return_value.st_size=20
            st.return_value.st_mtime=mod.time.time()
            fp=op.return_value.__enter__.return_value
            fp.read.return_value=b'Traceback\nsecret_token=123\nModuleNotFoundError: password'
            obj=mod.log_summary()
        self.assertEqual(obj["last_known_marker"],"IMPORT_MODULE_MISSING")
        self.assertNotIn("secret_token",str(obj))
        self.assertNotIn("password",str(obj))

    def test_output_contains_no_secret(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            mod.emit("SAMPLE", http=None, transport="CONNECTION_REFUSED")
        self.assertEqual(json.loads(output.getvalue())["transport"],"CONNECTION_REFUSED")

if __name__ == '__main__': unittest.main()
