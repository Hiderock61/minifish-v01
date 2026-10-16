"""One Issue -> three fixed, public-only MiniFish observations.

No arbitrary destinations, AI planning, sessions, login or external writes.
Each existing single-page probe still makes its own SupervisorGate checks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .public_sites import PUBLIC_SITES, observed_url_allowed
from .readonly_probe import run_public_readonly

BATCH_KEYS = ("example", "python", "github")


def run_registered_batch(*, issue_number: int, output_root: Path) -> dict[str, Any]:
    if type(issue_number) is not int or not 1 <= issue_number <= 2_000_000_000:
        raise ValueError("INVALID_ISSUE_NUMBER")
    root = Path(output_root)
    sites: list[dict[str, Any]] = []
    for key in BATCH_KEYS:
        site = PUBLIC_SITES[key]
        try:
            # Each site gets an isolated new browser with no persisted profile.
            data = run_public_readonly(
                job_id=f"batch_{issue_number}_{key}",
                goal="Read the already-approved public site without interaction",
                url=site.url,
                run_dir=root / f"issue_{issue_number}" / key,
            )
            passes = (
                data.get("status") == "PASS"
                and data.get("supervisor_pass") is True
                and data.get("api_calls") == 0
                and data.get("paid_calls") == 0
                and data.get("external_writes") == 0
                and data.get("credential_access") == 0
                and data.get("browser_actions_executed") == 0
                and observed_url_allowed(site, str(data.get("observed_url", "")))
                and bool(data.get("run_id"))
            )
            sites.append({
                "site": key,
                "status": "PASS" if passes else "FAIL",
                "run_id": str(data.get("run_id", ""))[:80] if passes else "",
                "title": str(data.get("title", ""))[:120] if passes else "",
            })
        except Exception:
            # No exception or browser/page content escapes into public comments.
            sites.append({"site": key, "status": "FAIL", "run_id": "", "title": ""})

    all_pass = len(sites) == len(BATCH_KEYS) and all(
        site["status"] == "PASS" for site in sites
    )
    return {
        "status": "PASS" if all_pass else "FAIL",
        "route": "fixed_public_batch_v1",
        "sites_expected": len(BATCH_KEYS),
        "sites_checked": len(sites),
        "sites": sites,
        "api_calls": 0,
        "paid_calls": 0,
        "external_writes": 0,
        "credential_access": 0,
        "browser_actions_executed": 0,
        "ai_planner": "DISABLED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", type=int, required=True)
    args = parser.parse_args()
    report = run_registered_batch(
        issue_number=args.issue_number,
        output_root=Path(".minifish/batch"),
    )
    Path("batch_public_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print("MINIFISH_BATCH_RESULT status=" + report["status"])
    for site in report["sites"]:
        print(f"  {site['site']}: {site['status']}")
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
