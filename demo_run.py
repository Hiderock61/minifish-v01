from __future__ import annotations

from pathlib import Path
import json

from minifish import Action, ScriptedPlanner, MiniFishRunner

ROOT = Path(__file__).parent
LOG = ROOT / "run_logs" / "demo_run.json"
CAPTURE = ROOT / "run_logs" / "captures"

DEMO_HTML = r'''
<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>MiniFish Demo</title></head>
<body>
<h1>MiniFish Demo</h1>
<button id="open-profile">プロフィール</button>
<script>
document.getElementById('open-profile').addEventListener('click', () => {
  location.hash = 'profile';
  document.body.innerHTML = `
    <h1>プロフィール編集</h1>
    <label for="display-name">表示名</label>
    <input id="display-name" aria-label="表示名" type="text">
    <button id="save">保存</button>`;
  document.getElementById('save').addEventListener('click', () => {
    const name = document.getElementById('display-name').value;
    location.hash = 'saved';
    document.body.innerHTML = `<h1>保存完了</h1><p>${name}</p>`;
  });
});
</script>
</body></html>
'''


def main():
    planner = ScriptedPlanner([
        Action(type="click", role="button", name="プロフィール", reason="goal requires profile editor"),
        Action(type="fill", role="textbox", name="表示名", value="ヒデロック", reason="fill target field"),
        Action(type="click", role="button", name="保存", reason="submit form"),
        Action(type="done", result="プロフィールを保存完了", reason="success page observed"),
    ])

    runner = MiniFishRunner(
        planner,
        max_steps=10,
        max_duration_seconds=30,
        headless=True,
        capture_dir=str(CAPTURE),
        log_path=str(LOG),
    )
    state = runner.run(
        goal="プロフィール編集画面を開き、表示名をヒデロックにして保存する",
        start_url="about:blank",
        start_html=DEMO_HTML,
    )

    print(json.dumps({
        "run_id": state.run_id,
        "status": state.status,
        "steps": state.step_count,
        "result": state.final_result,
        "error": state.error,
        "log": str(LOG),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
