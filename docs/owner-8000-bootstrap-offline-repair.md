# MiniFish 8000: browser-free repair candidate (2026-11-01)

## Status and scope

**OFFLINE_IMPLEMENTED / LOCAL_QA_PASS / CODESPACE_NOT_DEPLOYED**

Based on PR #33 (`a3549bb18db802c14b24f2a47860eb6ed491ecf9`) and the existing independently stored owner probes, this proposal changes ONLY `start_all.sh`, adds `tools/api_bootstrap.py`, and adds `tests/test_api_bootstrap_contract.py`.

Prior live fact: three observations of `uvicorn_cloud_api=0`, no 8000 TCP listener, localhost CONNECTION_REFUSED; old `/tmp/minifish-api.log` was zero bytes. It **does not prove** postStart never executed or establish the original root cause.

## Offline implementation

- The existing devcontainer postStartCommand still invokes `bash start_all.sh`.
- For Codespaces only, `start_all.sh` invokes `python tools/api_bootstrap.py --ensure` and propagates failure as a nonzero postStart exit status; the existing bridge launch is retained.
- A fixed-code startup receipt is stored as 0600 inside the private 0700 directory `~/.local/share/minifish/api-bootstrap/`. The receipt records UTC time, fixed status and a bounded child exit code; it contains no nonce, credentials or response body.
- Duplicate safety: nonblocking flock, accurate argv match to an existing Uvicorn owner process, refusal to launch when port 8000 is occupied by an unknown service, no kill, no automatic repeated restart.
- A single launch calls the unchanged `bash start_iphone.sh`; checks actual owner HTTP response for up to 16 seconds. A launched child that exits early records `FAIL_CHILD_EXITED` and numeric exit code.
- `python tools/api_bootstrap.py --status` is **read-only**. It shows a fixed saved receipt plus **fresh** localhost port state / HTTP readiness, and does not conflate historical READY with current READY.
- Private ports 8000/8002/6081, repo source identity and Codespace environment are checked before launching. G1b/VNC/Chromium never auto-starts.
- Existing local development behavior outside Codespaces remains available.

## Fixed results

READY_ALREADY / READY_SPAWNED: current HTTP response confirmed.
HOLD_PORT_OCCUPIED: unrelated/unrecognized service on port 8000.
HOLD_PROCESS_PRESENT: known owner process not yet ready; no second spawn.
HOLD_TIMEOUT_ALIVE: spawned process still alive but HTTP readiness not reached within window.
FAIL_CHILD_EXITED: spawned process exited before readiness; private receipt includes exit code.
FAIL_TIMEOUT_EXITED: process exited exactly at readiness deadline.
HOLD_NOT_CODESPACE / HOLD_PRIVATE_PORTS / HOLD_PRIVATE_DIRECTORY / HOLD_SOURCE_MISMATCH / HOLD_LOCK_BUSY: launch guard blocked.
Private raw Uvicorn log is retained in the same 0700 directory, but **never copy raw log into chat, GitHub, Notion or public reports**.

## Tests already run locally (NOT GitHub CI)

Python unittest discovery of `tests/test_api_bootstrap.py`, `tests/test_api_bootstrap_contract.py` and `tests/test_start_all_integration.py`: **39 tests PASS, 0 FAIL**. These are mocked service tests and fake-command Bash integration. No Codespace, GitHub Actions, external websites or paid browser was started.

The GitHub branch contains the smaller `test_api_bootstrap_contract.py` subset; additional local tests are packaged separately as an offline ZIP. Run the full repository suite in a trusted CI/Work environment only when separately authorized.

## One future deployment step, NOT performed

Do not mistake this independent GitHub branch for the running Codespace. It has **NOT** been applied to `accursed apparition`. In a separate approved maintenance window, Work can inspect the branch diff and clean working tree, apply this isolated repair to the **existing target only**, then observe `--status` and localhost HTTP 200. Do not create a new Codespace, touch the legacy `glorious disco`, merge PR #33/main, or turn on automatic Runtime/CrowdWorks login.

If HTTP 200 returns, the pre-existing owner Runtime acceptance probe can advance to its nonce-protected single POST under an explicit, separate acceptance step. Only actual Chromium visualization of the CrowdWorks login page can prove `MINIFISH_BROWSER_REAL_PASS`.

## Cost / operational boundary

No TinyFish, Work cloud browser, Codespace start, GitHub Actions run, paid API or cloud browsing was used to develop this patch. GitHub Codespaces still incurs running-machine/storage allowances or costs after deployment; this patch does not make hosting free.
