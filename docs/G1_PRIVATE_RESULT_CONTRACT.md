# MiniFish G1 | Private result handoff contract (synthetic-only)

## Status and scope
This document defines a **mock in-process transport contract only**. It is **NOT** a deployed ChatGPT-to-Codespace channel, HTTP endpoint, or CrowdWorks reader. The real owner's Codespace/Vault/keys and all external websites remain untouched.

### Why a private result channel is necessary
The repository `Hiderock61/minifish-v01` is public. Existing GitHub Issues/PR comments and Actions logs must not receive any authenticated page titles, account details, cookies, vault contents, key material, or bearer capabilities. Even a count can reveal metadata, so the new public receipt contains no title counts.

## Proposed separation
1. **Public control plane**: An owner-authored job identifier and a fixed, non-sensitive receipt `PRIVATE_RESULT_READY`. No direct URL/capability to a private result.
2. **Private data plane (only simulated in this PR)**: An in-memory `PrivateResultMailbox` receives only validated, extracted synthetic title strings, not HTML, browser snapshots, credentials, or a Vault.
3. **Trusted receiver (only simulated in this PR)**: A test-local caller independently holds a high-entropy capability. A matching job id and capability can claim the result exactly once, within a bounded lifetime. A wrong capability, replay, duplicate job, malformed title, or expired request stops safely.
4. **No persistence**: The mailbox holds the fake payload only in process memory and drops references on claim or expiry. It is not durable and does not guarantee secure erasure from Python memory.

## Isolation
- Existing `bridge_worker.run_job` retains all production modes unchanged.
- New `owner_private_delivery_mock` mode requires `MINIFISH_G1_PRIVATE_MOCK_E2E=1`, an active pytest context, and **no `CODESPACE_NAME`**. It also requires an explicitly injected in-memory mailbox from the test. The normal Codespace Bridge cannot invoke it.
- Only the fixed synthetic command `READ_SYNTHETIC_JOB_TITLES` is accepted; URLs and arbitrary goals are rejected before any browser.
- The browser remains local to `127.0.0.1`, using an ephemeral synthetic Cookie and temporary encrypted Vault. The Vault remains byte-identical after the read.
- The public receipt has an allowlisted shape and never contains title values, title counts, Cookie values, the claimant's secret, or the private payload.

## Test expectations
- CI `MiniFish tests`: offline contract tests and existing regression suite.
- CI `MiniFish G1 encrypted mock session acceptance`: actual Playwright Chromium + mock HTTP site, fake encrypted session restoration, title extraction, one-time private handoff, public receipt checks.
- G1b CI: pre-existing private UI browser acceptance should remain successful.
- Skip results must remain labeled SKIP, not PASS.

## Not yet solved
The real ChatGPT conversation has **no independently verified private tool/action to authenticate to and read this in-memory mailbox in the running Codespace**. No cross-process network transport, token provisioning to ChatGPT, process restart persistence, real-site page parsing/consent, or authenticated user readout is implemented. These require explicit capability discovery and a separate security review before any real data are used. Do not put the capability in GitHub Issues, comments, Actions artifacts, code, a query string, or logs.

## Promotion gate
This proof of concept may only advance when:
- GitHub CI actually passes on this isolated branch.
- The PR remains draft/unmerged until explicitly approved.
- A privately authenticated delivery mechanism usable *from this chat* is verified and can be tested entirely with synthetic data.
- The owner authorizes a separate real-site read-only trial after a no-leak review.

**Read-only mock PASS never means the live ChatGPT-to-CrowdWorks flow is ready.**
