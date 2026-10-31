"""Offline-only regression of the Codespaces one-shot HTTP owner bootstrap."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boot_under_test', ROOT/'tools/api_bootstrap.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)

class Child:
    def __init__(self, result=None): self.result = result
    def poll(self): return self.result

class BootContract(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.d = Path(td.name)
        repo = self.d/'repo'
        repo.mkdir()
        for f in ('cloud_api.py','start_iphone.sh','start_all.sh'):
            (repo/f).write_text('')
        (repo/'.devcontainer').mkdir()
        self.config = repo/'.devcontainer/devcontainer.json'
        self.config.write_text(json.dumps({'postStartCommand':'bash start_all.sh',
            'portsAttributes': {str(p):{'visibility':'private'} for p in (8000,8002,6081)}}))
        store = self.d/'home/.local/share/minifish/api-bootstrap'
        for field, value in [('ROOT',repo),('STORAGE',store),('RECEIPT',store/'status.json'),
                             ('LOG',store/'uvicorn.log'),('LOCK',store/'bootstrap.lock')]:
            p=patch.object(boot,field,value)
            p.start(); self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'CODESPACE_NAME':'accursed-apparition-6q7jwqq5965h4rpq'})
        p.start(); self.addCleanup(p.stop)

    def test_source_guard(self): self.assertIsNone(boot.source_guard())
    def test_no_codespace(self):
        with patch.dict(os.environ,{'CODESPACE_NAME':''}):
            self.assertEqual(boot.source_guard(),'HOLD_NOT_CODESPACE')
    def test_private_ports_only(self):
        c=json.loads(self.config.read_text()); c['portsAttributes']['6081']['visibility']='public'
        self.config.write_text(json.dumps(c))
        self.assertEqual(boot.source_guard(),'HOLD_PRIVATE_PORTS')
    def test_wrong_poststart(self):
        c=json.loads(self.config.read_text()); c['postStartCommand']='other'
        self.config.write_text(json.dumps(c))
        self.assertEqual(boot.source_guard(),'HOLD_SOURCE_MISMATCH')
    def test_private_permissions(self):
        self.assertTrue(boot.secure_storage())
        self.assertEqual(stat.S_IMODE(boot.STORAGE.stat().st_mode),0o700)
        boot.STORAGE.chmod(0o755)
        self.assertFalse(boot.secure_storage())
    def test_symlink_private_dir(self):
        boot.STORAGE.parent.mkdir(parents=True)
        boot.STORAGE.symlink_to(boot.STORAGE.parent)
        self.assertFalse(boot.secure_storage())
    def test_unknown_receipt(self):
        self.assertEqual(boot.read_receipt()['receipt'],'UNKNOWN')
    def test_secret_rejected_as_status(self):
        boot.secure_storage()
        with self.assertRaises(ValueError): boot.write_event('SECRET=123')
    def test_receipt_600_no_secrets(self):
        boot.secure_storage()
        with contextlib.redirect_stdout(io.StringIO()): boot.write_event('FAIL_CHILD_EXITED',exit_code=7)
        result=boot.read_receipt()
        self.assertEqual(result,{'receipt':'FAIL_CHILD_EXITED','exit_code':7})
        self.assertEqual(stat.S_IMODE(boot.RECEIPT.stat().st_mode),0o600)
    def test_stale_ready_never_actual_ready(self):
        boot.secure_storage()
        with contextlib.redirect_stdout(io.StringIO()): boot.write_event('READY_SPAWNED')
        out=io.StringIO()
        with patch.object(boot,'owner_http_ok',return_value=False),patch.object(boot,'port_open',return_value=False),contextlib.redirect_stdout(out):
            boot.status_only()
        self.assertEqual(json.loads(out.getvalue())['http_ready_now'],False)
    def test_no_start_when_already_ready(self):
        with patch.object(boot,'owner_http_ok',return_value=True),patch.object(boot.subprocess,'Popen',side_effect=AssertionError('spawn')):
            self.assertEqual(boot.start_once(1),'READY_ALREADY')
    def test_no_start_if_unknown_service(self):
        with patch.object(boot,'owner_http_ok',return_value=False),patch.object(boot,'port_open',return_value=True),patch.object(boot.subprocess,'Popen',side_effect=AssertionError('spawn')):
            self.assertEqual(boot.start_once(1),'HOLD_PORT_OCCUPIED')
    def test_no_start_if_owner_process_exists(self):
        with patch.object(boot,'owner_http_ok',return_value=False),patch.object(boot,'port_open',return_value=False),patch.object(boot,'existing_owner_process',return_value=True),patch.object(boot.subprocess,'Popen',side_effect=AssertionError('spawn')):
            self.assertEqual(boot.start_once(1),'HOLD_PROCESS_PRESENT')
    def test_one_spawn_and_verify_http(self):
        ready=iter([False,False,True]); calls=[]
        def popen(*args,**kwargs): calls.append(args); return Child()
        with patch.object(boot,'owner_http_ok',side_effect=lambda:next(ready)),patch.object(boot,'port_open',return_value=False),patch.object(boot,'existing_owner_process',return_value=False),patch.object(boot.subprocess,'Popen',side_effect=popen):
            self.assertEqual(boot.start_once(.3,.01),'READY_SPAWNED')
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],['bash','start_iphone.sh'])
    def test_record_child_exit_code(self):
        with patch.object(boot,'owner_http_ok',return_value=False),patch.object(boot,'port_open',return_value=False),patch.object(boot,'existing_owner_process',return_value=False),patch.object(boot.subprocess,'Popen',return_value=Child(13)):
            self.assertEqual(boot.start_once(.3,.01),'FAIL_CHILD_EXITED')
        self.assertEqual(boot.read_receipt()['exit_code'],13)
    def test_shell_syntax(self):
        self.assertEqual(subprocess.run(['bash','-n',str(ROOT/'start_all.sh')]).returncode,0)
    def test_g1b_must_not_autostart(self):
        script=(ROOT/'start_all.sh').read_text()
        self.assertNotIn('nohup bash start_g1b_mock.sh',script)
        self.assertIn('bash start_iphone.sh',script)
        self.assertIn('python bridge_worker.py',script)

if __name__=='__main__': unittest.main()
