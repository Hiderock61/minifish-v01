"""One-shot entrypoint for the MiniFish command tower's INTERNAL mock only."""
from __future__ import annotations

import json
import sys

from .command_tower import Mission, MiniFishCommandTower


def main() -> int:
    tower = MiniFishCommandTower()
    order = Mission(job_id="BONSAI_TOWER_001", goal="内部テスト画面で保存完了を確認")
    result = tower.execute(order)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
