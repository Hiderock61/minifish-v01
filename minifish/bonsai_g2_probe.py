"""G2 no-cost mock and explicit-opt-in official API single-turn probe."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from .chatgpt_api_adapter import MockResponsesClient, send_one_prompt

G2_PUBLIC_FIXTURE = "接続テストです。READYという一語だけを返してください。"


def run_probe(mode: str, *, allow_billable: bool = False,
              output_dir: str | Path = "bonsai_g2_evidence") -> dict:
    if mode not in ("mock", "live"):
        raise ValueError("unsupported_mode")
    if mode == "live":
        if not allow_billable or os.getenv("MINIFISH_G2_REAL_API_CONSENT") != "yes":
            raise PermissionError("live_api_requires_explicit_consent")
        if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"):
            raise RuntimeError("missing_openai_api_key_or_model")
        from openai import OpenAI
        client = OpenAI(max_retries=0, timeout=30.0)
        model = os.environ["OPENAI_MODEL"]
        transport = "openai_responses_api"
    else:
        client = MockResponsesClient()
        model = "mock-no-model"
        transport = "mock_only"

    d = send_one_prompt(client, model=model, prompt=G2_PUBLIC_FIXTURE,
                        transport=transport, max_output_tokens=128)
    verified = d.status == "PASS" and d.raw_text.strip() == "READY"
    report = {
        "run_id": "g2_" + uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if verified else "FAIL",
        "mode": mode,
        "api_called": mode == "live",
        "prompt_sha256": hashlib.sha256(G2_PUBLIC_FIXTURE.encode("utf-8")).hexdigest(),
        "checks": {"has_output": d.status == "PASS", "fixed_ready_returned": verified,
                   "single_call": len(client.calls) == 1 if mode == "mock" else True},
        "delivery": d.public_summary(),
        "readiness": "MOCK_TRANSPORT_PASS_NOT_LIVE_CONNECT" if mode == "mock"
                     else "LIVE_API_SINGLE_TURN_PASS" if verified else "LIVE_UNVERIFIED",
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # Never put a live private raw transcript into public Actions artifacts.
    if mode == "mock":
        (out / "mock_transcript.txt").write_text(d.raw_text, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--output-dir", default="bonsai_g2_evidence")
    args = parser.parse_args()
    report = run_probe(args.mode, allow_billable=args.allow_billable, output_dir=args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
