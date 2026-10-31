"""Isolated tests: never open network sockets or send an owner start request."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "owner_runtime_accept.py"
spec = importlib.util.spec_from_file_location("minifish_local_accept", SCRIPT)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
NONCE = "private-DO-NOT-LOG-" + "Z" * 48


class AcceptanceTest(unittest.TestCase):
    def capture(self, *, start, responses, home=200, ready=True):
        events = []
        requests = []
        def fake_request(method, path, *, payload=None):
            requests.append((method, path, payload))
            if not responses:
                raise AssertionError("Unexpected request")
            return responses.pop(0)
        buf = io.StringIO()
        with patch.object(app, "json_request", side_effect=fake_request), patch.object(app, "http_probe", side_effect=lambda port, path: home if port == 8000 else 200), patch.object(app, "tcp_probe", return_value=ready), patch.object(app.time, "sleep", return_value=None), contextlib.redirect_stdout(buf):
            result = app.run(start=start, wait_seconds=2, interval=1)
        output = buf.getvalue()
        events = [json.loads(s) for s in output.splitlines()]
        self.assertNotIn(NONCE, output)
        self.assertNotIn("start_nonce", output)
        return result, events, requests

    def test_read_only_default_does_not_post(self):
        r, e, req = self.capture(start=False, responses=[(200, {"status":"STOPPED","can_start":True,"start_nonce":NONCE})])
        self.assertEqual(r, 0)
        self.assertEqual(len(req), 1)
        self.assertEqual(e[-1]["verdict"], "INITIAL_STATE_PASS_READ_ONLY")

    def test_exactly_one_post_then_ready(self):
        r, e, req = self.capture(start=True, responses=[(200,{"status":"STOPPED","can_start":True,"start_nonce":NONCE}),(200,{"status":"STARTING","can_start":False}),(200,{"status":"READY","can_start":False})])
        self.assertEqual(r, 0)
        self.assertEqual([q[0] for q in req], ["GET", "POST", "GET"])
        self.assertEqual(req[1][2], {"nonce":NONCE})
        self.assertEqual(e[-1]["verdict"], "RUNTIME_LOCAL_PASS_CHROMIUM_UNVERIFIED")
        self.assertEqual(next(x for x in e if x["event"] == "POST_RESPONSE")["owner_post_count"], 1)

    def test_nonce_missing_no_post(self):
        r,e,req=self.capture(start=True,responses=[(200,{"status":"STOPPED","can_start":True})])
        self.assertEqual(r,2)
        self.assertEqual(len(req),1)
        self.assertEqual(e[-1]["verdict"],"HOLD_NONCE_MISSING")

    def test_gate_not_stopped_no_post(self):
        r,e,req=self.capture(start=True,responses=[(200,{"status":"OFFLINE","can_start":False,"start_nonce":NONCE})])
        self.assertEqual(r,2)
        self.assertEqual(len(req),1)

    def test_auth_403_reports_only_fixed_code(self):
        r,e,req=self.capture(start=True,responses=[(200,{"status":"STOPPED","can_start":True,"start_nonce":NONCE}),(403,{"detail":"OWNER_START_PROOF_REQUIRED","nonce":"should-never-appear"})])
        self.assertEqual(r,3)
        self.assertEqual(e[-1]["verdict"],"FAIL_START_AUTH")
        self.assertEqual(len([v for v in req if v[0]=="POST"]),1)
        self.assertNotIn("should-never-appear",str(e))

    def test_local_8000_unavailable_no_post(self):
        r,e,req=self.capture(start=True,responses=[],home=502)
        self.assertEqual(r,2)
        self.assertEqual(e[-1]["verdict"],"FAIL_8000")
        self.assertFalse(req)

    def test_fixed_start_failure_no_second_request(self):
        r,e,req=self.capture(start=True,responses=[(200,{"status":"STOPPED","can_start":True,"start_nonce":NONCE}),(200,{"status":"DESKTOP_MISSING","can_start":False})])
        self.assertEqual(r,3)
        self.assertEqual(e[-1]["verdict"],"FAIL_PRE_VNC")
        self.assertEqual(len(req),2)

    def test_unknown_status_not_exfiltrated(self):
        self.assertIsNone(app.code("some-secret=ey..."))
        self.assertIsNone(app.code("lowercase"))
        self.assertIsNone(app.code("A"*81))
        self.assertIsNone(app.code("POSSIBLY_SENSITIVE_DATA"))
        self.assertEqual(app.filtered({"status":"READY", "nonce":NONCE}), {"status":"READY", "can_start":None,"fixed_detail":None})

    def test_no_external_path(self):
        with self.assertRaises(ValueError):
            app.json_request("POST", "/danger", payload={"nonce":NONCE})
        with self.assertRaises(ValueError):
            app.http_probe(443,"/")

    def test_post_http_failure(self):
        r,e,req=self.capture(start=True,responses=[(200,{"status":"STOPPED","can_start":True,"start_nonce":NONCE}),(500,{"detail":"SERVER_ERROR"})])
        self.assertEqual(r,3)
        self.assertEqual(e[-1]["verdict"],"FAIL_START_HTTP")


if __name__ == "__main__":
    unittest.main()
