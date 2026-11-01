"""Offline tests. Only chmods temporary throwaway directories."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODFILE=Path(__file__).resolve().parents[1]/'tools/private_dir_mode_repair.py'
spec=importlib.util.spec_from_file_location('private_dir_mode_repair',MODFILE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NAME='accursed-apparition-6q7jwqq5965h4rpq'
PORTS={'state':'READABLE', 'active':[]}
OK={'state':'READABLE','roles':['owner_api','bridge'],
    'different_owner_roles':[],'unreadable_processes':0}

class RepairTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)/'home'
        p=self.home/'.local/share/minifish'
        p.mkdir(parents=True)
        p.chmod(0o755)
        self.p=p
        env=patch.dict(os.environ,{'CODESPACE_NAME':NAME})
        env.start();self.addCleanup(env.stop)

    def execute(self,apply=False,processes=None):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            result=m.repair(apply=apply,home=self.home,processes=processes or OK,listeners=PORTS)
        obj=json.loads(output.getvalue())
        return result,obj

    def test_read_does_not_modify(self):
        result,obj=self.execute()
        self.assertEqual(result,'READY_TO_RESTRICT')
        self.assertEqual(self.p.stat().st_mode & 0o777,0o755)
        self.assertEqual(obj['directory_changes'],0)

    def test_changes_single_directory_only(self):
        child=self.p/'api-bootstrap';child.mkdir(); child.chmod(0o700)
        result,obj=self.execute(apply=True)
        self.assertEqual(result,'CHMOD_0700_VERIFIED')
        self.assertEqual(self.p.stat().st_mode & 0o777,0o700)
        self.assertEqual(child.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.p.parent).stat().st_mode & 0o777,0o755)
        self.assertEqual(obj['directory_changes'],1)
        self.assertEqual(obj['owner_post_count'],0)

    def test_idempotent(self):
        self.execute(apply=True)
        result,obj=self.execute(apply=True)
        self.assertEqual(result,'ALREADY_0700')
        self.assertEqual(obj['directory_changes'],0)

    def test_anomalous_mode_holds(self):
        self.p.chmod(0o750)
        result,obj=self.execute(apply=True)
        self.assertEqual(result,'HOLD_UNEXPECTED_MODE')
        self.assertEqual(self.p.stat().st_mode & 0o777,0o750)

    def test_other_owner_service_holds(self):
        other={**OK,'different_owner_roles':['owner_api']}
        result,_=self.execute(apply=True,processes=other)
        self.assertEqual(result,'HOLD_SHARED_SERVICE_OTHER_OWNER')
        self.assertEqual(self.p.stat().st_mode & 0o777,0o755)

    def test_proc_unavailable_holds(self):
        bad={**OK,'state':'PROC_UNAVAILABLE'}
        result,_=self.execute(apply=True,processes=bad)
        self.assertEqual(result,'HOLD_PROCESS_SCAN_INCOMPLETE')

    def test_symlink_target_holds(self):
        self.p.rmdir()
        self.p.symlink_to(self.home)
        result,_=self.execute(apply=True)
        self.assertEqual(result,'HOLD_PATH_UNSAFE_OR_UNREADABLE')

    def test_symlink_parent_holds(self):
        self.p.rmdir();self.p.parent.rmdir()
        (self.home/'.local/share').symlink_to(self.home)
        result,_=self.execute(apply=True)
        self.assertEqual(result,'HOLD_PATH_UNSAFE_OR_UNREADABLE')

    def test_wrong_codespace_holds(self):
        with patch.dict(os.environ,{'CODESPACE_NAME':'glorious-disco-rqvjwqq6gpgcxr6j'}):
            result,_=self.execute(apply=True)
        self.assertEqual(result,'HOLD_WRONG_CODESPACE')
        self.assertEqual(self.p.stat().st_mode & 0o777,0o755)

    def test_known_role_strict(self):
        self.assertEqual(m.known_role([b'uvicorn',b'cloud_api:app']), 'owner_api')
        self.assertEqual(m.known_role([b'python',b'bridge_worker.py']),'bridge')
        self.assertIsNone(m.known_role([b'python',b'SECRET_bridge_worker.py_suffix']))

    def test_unknown_not_printed(self):
        (self.p/'secret.txt').write_text('SUPER_SECRET_CREDENTIAL')
        _,obj=self.execute()
        self.assertNotIn('SUPER_SECRET_CREDENTIAL',str(obj))
        self.assertNotIn(str(self.home),str(obj))

    def test_runtime_active_holds(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            result=m.repair(apply=True,home=self.home,processes=OK,
                            listeners={'state':'READABLE','active':['novnc_6081']})
        self.assertEqual(result,'HOLD_RUNTIME_ACTIVE_OR_PARTIAL')
        self.assertEqual(self.p.stat().st_mode & 0o777,0o755)

    def test_runtime_port_table_unknown_holds(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            result=m.repair(apply=True,home=self.home,processes=OK,
                            listeners={'state':'UNKNOWN','active':[]})
        self.assertEqual(result,'HOLD_RUNTIME_PORTS_UNKNOWN')

    def test_check_reads_processes_only(self):
        with patch.object(m,'check_process_owners',return_value=OK):
            result,obj=self.execute(processes=None)
        self.assertEqual(result,'READY_TO_RESTRICT')
        self.assertEqual(obj['processes']['roles'],['owner_api','bridge'])

if __name__=='__main__':unittest.main()
