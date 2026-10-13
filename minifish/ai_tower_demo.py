"""MiniFish AI-tower entrypoint. Mock default; live requires double consent."""
from __future__ import annotations

import argparse
import json

from .ai_tower import run_ai_tower_trial


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--job-id", default="BONSAI_AI_TOWER_001")
    args = parser.parse_args()
    result = run_ai_tower_trial(args.job_id, mode=args.mode,
                                approved=args.allow_billable)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["state"] != "COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
