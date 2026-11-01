"""Offline-only security and classifier tests; no Chromium or site opened."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/"tools/chromium_gui_read.py"
spec=importlib.util.spec_from_file_location("chromium_gui_read",SOURCE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class GuiProofTests(unittest.TestCase):
    def test_class_chromium_only(self):
        self.assertTrue(m.is_chromium_class('WM_CLASS(STRING) = "chromium", "Chromium-browser"'))
        self.assertTrue(m.is_chromium_class('WM_CLASS(STRING) = "google-chrome", "Google-chrome"'))
        self.assertFalse(m.is_chromium_class('WM_CLASS(STRING) = "firefox", "Firefox"'))
        self.assertFalse(m.is_chromium_class('_NET_WM_NAME(UTF8_STRING) = "chromium"'))

    def test_pid_parse(self):
        self.assertEqual(m.read_pid('_NET_WM_PID(CARDINAL) = 1234\n'),1234)
        self.assertIsNone(m.read_pid('_NET_WM_PID: 987'))

    def test_is_viewable_with_real_geometry(self):
        self.assertTrue(m.window_viewable('Map State: IsViewable\n Width: 1280\n Height: 768'))
        self.assertFalse(m.window_viewable('Map State: IsUnMapped\n Width: 1280\n Height: 768'))
        self.assertFalse(m.window_viewable('Map State: IsViewable\n Width: 10\n Height: 768'))

    def test_source_identity_not_unverified(self):
        self.assertEqual(set(m.EXPECTED_BLOBS),{"minifish/crowdworks_handoff.py","g1b_mock_app.py"})
        self.assertTrue(all(len(x)==40 for x in m.EXPECTED_BLOBS.values()))

    def test_wrong_codespace_blocks(self):
        with patch.dict(os.environ,{"CODESPACE_NAME":"glorious-disco-rqvjwqq6gpgcxr6j"}), self.assertRaises(m.Hold) as e:
            m.gate()
        self.assertEqual(str(e.exception),"HOLD_WRONG_CODESPACE")

    def test_no_external_urls_in_read_code(self):
        code=SOURCE.read_text()
        self.assertNotIn("https://crowdworks.jp",code)
        self.assertNotIn("urlopen(Request('https://",code)
        self.assertNotIn("page.screenshot",code)
        self.assertNotIn("POST",code.split("def owner_status")[1].split("def run_cmd")[0].replace('"POST"',""))

    def test_owner_status_discard_nonce(self):
        class Reply:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"status":"WAITING_FOR_HUMAN","action_nonce":"HIDDEN_PASSWORD_VALUE"}'
        with patch.object(m.OPENER,"open",return_value=Reply()):
            self.assertEqual(m.owner_status(),"WAITING_FOR_HUMAN")

    def test_owner_status_unknown_not_printed(self):
        class Reply:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"status":"SENSITIVE_SECRET"}'
        with patch.object(m.OPENER,"open",return_value=Reply()):
            self.assertEqual(m.owner_status(),"STATUS_UNKNOWN")

    def test_no_chromium_does_not_pass(self):
        with patch.object(m,"gate"),patch.object(m,"owner_status",return_value="WAITING_FOR_HUMAN"),patch.object(m,"windows",return_value=[]):
            verdict,fields=m.inspect()
        self.assertEqual(verdict,"LOGIN_NAVIGATION_COMPLETE_X11_WINDOW_UNCONFIRMED")
        self.assertFalse(fields["real_page_pixels_inspected"])

    def test_chromium_mapped_and_status(self):
        with patch.object(m,"gate"),patch.object(m,"owner_status",return_value="WAITING_FOR_HUMAN"),patch.object(m,"windows",return_value=["0x12"]),patch.object(m,"run_cmd",side_effect=[
            'WM_CLASS(STRING) = "chromium","Chromium"\n_NET_WM_PID(CARDINAL) = 1234\n',
            'Map State: IsViewable\nWidth: 900\nHeight: 700',
        ]),patch.object(m,"owned_chromium",return_value=True):
            verdict,fields=m.inspect()
        self.assertEqual(verdict,"CHROMIUM_WINDOW_MAPPED_LOGIN_NAVIGATION_COMPLETE_PIXELS_UNVERIFIED")
        self.assertTrue(fields["chromium_pid_owner_verified"])
        self.assertFalse(fields["real_page_pixels_inspected"])

    def test_mapped_without_login_not_full_pass(self):
        with patch.object(m,"gate"),patch.object(m,"owner_status",return_value="LOGIN_NOT_STARTED"),patch.object(m,"windows",return_value=["0x12"]),patch.object(m,"run_cmd",side_effect=[
            'WM_CLASS(STRING) = "Chromium"\n_NET_WM_PID(CARDINAL) = 1234\n',
            'Map State: IsViewable\nWidth: 900\nHeight: 700',
        ]),patch.object(m,"owned_chromium",return_value=True):
            verdict,_=m.inspect()
        self.assertEqual(verdict,"CHROMIUM_WINDOW_MAPPED_LOGIN_STATE_UNCONFIRMED")

    def test_wm_class_not_enough_without_pid(self):
        with patch.object(m,"gate"),patch.object(m,"owner_status",return_value="WAITING_FOR_HUMAN"),patch.object(m,"windows",return_value=["0x12"]),patch.object(m,"run_cmd",return_value='WM_CLASS(STRING) = "chromium"\n'):
            verdict,fields=m.inspect()
        self.assertFalse(fields["chromium_pid_owner_verified"])
        self.assertEqual(verdict,"LOGIN_NAVIGATION_COMPLETE_X11_WINDOW_UNCONFIRMED")

    def test_print_only_fixed_allowlist(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            m.emit("CHROMIUM_WINDOW_MAPPED_LOGIN_NAVIGATION_COMPLETE_PIXELS_UNVERIFIED",owner_status="WAITING_FOR_HUMAN")
        result=json.loads(out.getvalue())
        self.assertFalse(result["secret_exposed"])
        self.assertEqual(result["screenshot_export_count"],0)
        self.assertNotIn("nonce",out.getvalue())

if __name__=="__main__":
    unittest.main()
