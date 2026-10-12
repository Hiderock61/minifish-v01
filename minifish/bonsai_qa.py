#!/usr/bin/env python3
"""BONSaY QA: MiniFish browser probe and optional Gemini FREE-tier API rehearsal.

Public sample only. No automated consumer-ChatGPT/Gemini UI scraping.
Results are evidence, not a claim of human-quality PASS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from minifish import Action, MiniFishRunner, ScriptedPlanner

PREVIEW = "https://hiderock61.github.io/bonsai/preview-ui-v02/"
ORIGINAL = "https://hiderock61.github.io/bonsai/"
T0 = "Uber Eats配達員が効率よく稼ぐにはどうしたらいい？"
MODEL = "gemini-2.5-flash-lite"
MAX_GENERATIONS = 2  # T0 -> T1 after a single あ; next question T2 is captured but not fired.
RUN_ROOT = Path("bonsai_qa_run")


class ExtractText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buffers = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "h1", "h2", "h3", "pre", "li", "div"):
            self.buffers.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag in ("p", "h1", "h2", "h3", "pre", "li"):
            self.buffers.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.buffers.append(data)

    def plain(self):
        return "\n".join(line.strip() for line in "".join(self.buffers).splitlines() if line.strip())


def get_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MiniFish-BONSaY-QA/0.1"})
    with urllib.request.urlopen(req, timeout=22) as res:
        raw = res.read(200000).decode("utf-8")
        status = res.status
    parser = ExtractText()
    parser.feed(raw)
    return status, raw, parser.plain()


def mini_observe():
    """A genuine MiniFish observation, NOT a replay of an AI-generated turn."""
    runner = MiniFishRunner(
        ScriptedPlanner([Action(type="done", result="Public BONSaY page observed; no input or writes")]),
        max_steps=1,
        max_duration_seconds=50,
        headless=True,
        capture_dir=str(RUN_ROOT / "capture"),
        log_path=str(RUN_ROOT / "minifish_run.json"),
    )
    state = runner.run(
        goal="Read the public BONSaY preview page once, no clicks or writes.",
        start_url=PREVIEW,
    )
    obs = state.events[0].observation if state.events else {}
    return {
        "status": str(state.status),
        "error": str(state.error or ""),
        "title": obs.get("title", ""),
        "url": obs.get("url", ""),
        "text_sample": obs.get("text_excerpt", "")[:350],
        "steps": state.step_count,
    }


def check_page(page_text, old_text):
    return {
        "preview_welcome_rule": "BONSaYへようこそ" in page_text,
        "natural_speech_layer": "公演人間語レイヤー" in page_text,
        "visual_summary_layer": "今回見えてきたこと" in page_text and "まだ決まっていないこと" in page_text,
        "structural_rules_present": all(k in page_text for k in ["反応元", "🆕", "🌿", "⚔️", "STOP"]),
        "legacy_ready_preserved": "🎭 BONSaY 現行候補 v0.1d｜READY" in old_text,
        "preview_is_distinct": page_text != old_text,
    }


def gemini_call(key, contents):
    data = json.dumps({
        "contents": contents,
        "generationConfig": {"temperature": 0.25, "maxOutputTokens": 4096},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + MODEL + ":generateContent",
        data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        details = e.read(450).decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API HTTP {e.code}: {details}") from e
    parts = []
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                parts.append(part["text"])
    text = "\n".join(parts).strip()
    if not text:
        raise RuntimeError("Gemini API returned no text; finishReason="+str(result.get("candidates", [{}])[0].get("finishReason")))
    return text


def evaluate_turn(text, phase):
    if phase == "welcome":
        checks = {
            "greeting": "BONSaYへようこそ" in text,
            "ready_to_listen": "準備" in text,
            "asks_question": "？" in text or "?" in text,
            "not_started_T0": "🌳 T0" not in text,
        }
    else:
        checks = {
            "multiple_roles_or_observations": text.count("🆕") >= 2,
            "surviving_branch": "🌿" in text,
            "next_natural_question": ("次に考えてみたい" in text or "次の更新トリガー" in text or "次の問い" in text),
            "readable_summary": "今回見えてきたこと" in text or "見えてきたこと" in text,
            "human_style_candidate": "「" in text or "」" in text,
        }
    return {"checks": checks, "formal_pass": all(checks.values()), "semantic_quality": "HUMAN_REVIEW_REQUIRED"}


def finish(result):
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    (RUN_ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"## 🐟 MiniFish BONSaY QA｜{result['mode']}",
        "",
        f"- Status: **{result['status']}**",
        f"- Run ID: \`{result['run_id']}\`",
        f"- Preview: {PREVIEW}",
        f"- Model: {result.get('model', 'none (browser probe only)')}",
        f"- Turns captured: {len(result.get('turns', []))}",
    ]
    for name, val in result.get("checks", {}).items():
        lines.append(f"- {'✅' if val else '❌'} {name}: {val}")
    for i, item in enumerate(result.get("turns", [])):
        lines.append(f"- GEN{i} {item['phase']}: formal_pass={item['evaluation']['formal_pass']} (human quality: unverified)")
        sample = " ".join(item["assistant"].split())[:520]
        lines.append(f"  - 回答抜粋: {sample}")
    lines.extend([
        "",
        "※ Browser probe PASS does **not** prove the AI has actually replied.",
        "※ API test is a legitimate model simulation with source page text attached, **not** the consumer-web-app UX.",
        "※ Full public example transcript and MiniFish browser evidence: Actions artifact.",
    ])
    if result.get("error"):
        lines.insert(5, "- Failure: " + result["error"][:320].replace("\n", " "))
    report = "\n".join(lines)
    (RUN_ROOT / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if result["status"] in ("PROBE_PASS", "API_FORMAL_PASS", "SKIPPED_NO_API_KEY") else 1


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--mode", choices=["probe", "gemini"], default="probe")
    args = cli.parse_args()
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    result = {
        "mode": args.mode,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + str(uuid.uuid4())[:8],
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "status": "STARTED",
        "checks": {},
        "turns": [],
    }
    try:
        code, html, page = get_page(PREVIEW)
        old_code, _, old = get_page(ORIGINAL)
        result["checks"] = check_page(page, old)
        result["checks"]["http_ok"] = code == 200 and old_code == 200
        if not all(result["checks"].values()):
            result["status"] = "PAGE_CONTRACT_FAIL"
            return finish(result)

        if args.mode == "probe":
            mini = mini_observe()
            result["mini_observation"] = mini
            result["checks"]["minifish_browser_observed_page"] = (
                "COMPLETED" in mini["status"].upper() and
                "BONSaY" in mini["title"] and
                not mini["error"]
            )
            result["status"] = "PROBE_PASS" if all(result["checks"].values()) else "BROWSER_PROBE_FAIL"
            return finish(result)

        # Never run paid provider unintentionally: require an existing Gemini key.
        key = os.getenv("GEMINI_API_KEY", "")
        result["model"] = MODEL
        if not key:
            result["status"] = "SKIPPED_NO_API_KEY"
            return finish(result)

        # The model is given the page content explicitly, not asked to scrape the consumer ChatGPT UI.
        # This checks runtime *behavior* at a different entry mode than URL-only launch.
        launch = (
            "以下はBONSaY実験用ページの全文です。全部を読み、最後の公演UX v0.2レイヤーを"
            "歓迎・発話・表示の仕様として優先し、BONSaY内部の観測・分岐・枝継承は維持してください。"
            "テーマを勝手に始めず、まずページに規定された歓迎の問いかけだけ返してください。\n\n"
            "=== BONSaY preview page begins ===\n" + page + "\n=== BONSaY preview page ends ==="
        )
        history = [{"role": "user", "parts": [{"text": launch}]}]
        sequence = [("welcome", None), ("T0", T0), ("T1", "あ")]
        for phase, user_text in sequence:
            if user_text is not None:
                history.append({"role": "user", "parts": [{"text": user_text}]})
            reply = gemini_call(key, history)
            ev = evaluate_turn(reply, phase)
            result["turns"].append({"phase": phase, "user": user_text or "(launch text)", "assistant": reply, "evaluation": ev})
            history.append({"role": "model", "parts": [{"text": reply}]})
            if not ev["formal_pass"]:
                result["status"] = "API_FORMAL_FAIL_" + phase
                break
            time.sleep(2)  # Gentle pace and no automatic retries.
        else:
            result["status"] = "API_FORMAL_PASS"
    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = f"{type(e).__name__}: {e}"
    return finish(result)


if __name__ == "__main__":
    sys.exit(main())
