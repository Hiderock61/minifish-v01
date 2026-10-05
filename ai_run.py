"""Run MiniFish with an OpenAI planning brain.

Required environment variables:
  OPENAI_API_KEY
  OPENAI_MODEL

Example:
  export OPENAI_API_KEY=...
  export OPENAI_MODEL=<model available to your API project>
  python ai_run.py https://example.com "Find the pricing page and tell me the cheapest plan"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from minifish import OpenAIPlanner, MiniFishRunner


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("goal")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--max-steps", type=int, default=25)
    args = p.parse_args()

    root = Path(__file__).parent
    planner = OpenAIPlanner()
    runner = MiniFishRunner(
        planner,
        max_steps=args.max_steps,
        headless=not args.headed,
        profile_path=str(root / "run_logs" / "profile.json"),
        capture_dir=str(root / "run_logs" / "ai_captures"),
        log_path=str(root / "run_logs" / "ai_run.json"),
    )
    state = runner.run(args.goal, args.url)
    print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
