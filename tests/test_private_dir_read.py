import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/private_dir_read.py'
spec = importlib.util.spec_from_file_location('private_dir_read', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
inspect_path, collect, decide, main = mod.inspect_path, mod.collect, mod.decide, mod.main


class PrivateDirReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.euid = os.geteuid()

    def test_missing(self):
        self.assertEqual(inspect_path(self.home/'none', self.euid)['type'], 'MISSING')

    def test_private_700(self):
        p=self.home/'.local/share/minifish'; p.mkdir(parents=True,mode=0o700)
        self.assertEqual(collect(self.home,self.euid)['verdict'], 'ROOT_MODE_OK_AT_READ_TIME_CAUSE_UNCONFIRMED')

    def test_parent_mkdir_755(self):
        p=self.home/'.local/share/minifish'; p.mkdir(parents=True,mode=0o755)
        self.assertEqual(collect(self.home,self.euid)['verdict'], 'ROOT_MODE_MISMATCH_MATCHES_REJECTION')

    def test_symlink_root(self):
        d=self.home/'.local/share'; d.mkdir(parents=True)
        (d/'minifish').symlink_to(self.home)
        self.assertEqual(collect(self.home,self.euid)['verdict'], 'ROOT_SYMLINK_MATCHES_REJECTION')

    def test_chmod_755(self):
        p=self.home/'.local/share/minifish'; p.mkdir(parents=True,mode=0o700); p.chmod(0o755)
        self.assertEqual(collect(self.home,self.euid)['entries']['minifish']['mode'],'0755')

    def test_no_path_contents(self):
        p=self.home/'.local/share/minifish'; p.mkdir(parents=True,mode=0o700)
        (p/'owner-desktop-boot.log').write_text('TOP_SECRET_TOKEN')
        output=json.dumps(collect(self.home,self.euid))
        self.assertNotIn('TOP_SECRET',output)

    def test_no_uid_disclosure(self):
        output=json.dumps(collect(self.home,self.euid))
        self.assertNotIn('"uid"',output)

    def test_wrong_codespace_gate(self):
        with patch.dict(os.environ,{'CODESPACE_NAME':'glorious-disco-rqvjwqq6gpgcxr6j'}),contextlib.redirect_stdout(io.StringIO()) as buf:
            r=main()
        self.assertEqual(r,2)
        self.assertEqual(json.loads(buf.getvalue())['verdict'],'HOLD_WRONG_CODESPACE')

    def test_root_missing_uncertain(self):
        self.assertEqual(collect(self.home,self.euid)['verdict'], 'ROOT_MISSING_AT_READ_TIME_CAUSE_UNCONFIRMED')

    def test_no_mutations(self):
        result=collect(self.home,self.euid)
        self.assertEqual(result['mutation_count'],0)
        self.assertEqual(result['owner_post_count'],0)


if __name__ == '__main__': unittest.main()
