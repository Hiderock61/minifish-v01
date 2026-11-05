import subprocess
import sys
from pathlib import Path

def test_runtime_secret_rotates_without_disclosure(tmp_path):
    script=(Path(__file__).resolve().parents[1]/"start_g1b_mock.sh").read_text()
    marker='python - "$private_dir/vnc-password.txt" <<\'PY\''
    code=script.split(marker,1)[1].split("\nPY",1)[0]
    path=tmp_path/"vnc-password.txt"
    for _ in range(2):
        previous=path.read_bytes() if path.exists() else None
        reply=subprocess.run([sys.executable,"-c",code,str(path)],capture_output=True,check=True)
        current=path.read_bytes()
        assert reply.stdout==b""
        assert reply.stderr==b""
        assert current != previous
        assert len(current)==8
        assert path.stat().st_mode & 0o777 == 0o600
