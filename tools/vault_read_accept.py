"""Validate local encrypted state without exporting credentials or cookies."""
import os
from pathlib import Path
import stat
import sys

def main():
    if os.getenv("CODESPACE_NAME") != "accursed-apparition-6q7jwqq5965h4rpq":
        raise ValueError()
    root=Path.home()/".local/share/minifish/owner-sessions"
    for path, directory in ((root,True),(root/"crowdworks.key",False),(root/"crowdworks.vault",False)):
        meta=path.lstat()
        assert not stat.S_ISLNK(meta.st_mode) and meta.st_uid==os.geteuid()
        assert stat.S_IMODE(meta.st_mode)==(0o700 if directory else 0o600)
        assert (stat.S_ISDIR(meta.st_mode) if directory else stat.S_ISREG(meta.st_mode))
    sys.path.insert(0,"/workspaces/minifish-v01")
    from minifish.crowdworks_handoff import _secret_vault
    state=_secret_vault().load()
    assert isinstance(state,dict)
    assert isinstance(state.get("cookies"),list) and isinstance(state.get("origins"),list)
    print("VAULT_DECRYPT_SCHEMA_PASS")
if __name__=="__main__":
    try:
        main()
    except Exception:
        print("HOLD_VAULT_VALIDATION")
        sys.exit(2)
