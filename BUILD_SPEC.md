# MiniFish v0.1 製作仕様札

## T0
自然言語のGOALを受け、Webページを観測し、次の1操作を決め、ブラウザへ実行し、結果を記録して、完了まで繰り返す最小Web Agentを1個作る。

## 利用者
司令塔ブラウザの研究・開発工程。TinyFishの「Agentのカラクリ」を外から眺めるだけでなく、自分で再構成して理解するための試験機。

## 使用場面
公開テストページや安全な検証用サイトで、GOAL → 観測 → 判断 → ACTION → RESULT のループを追跡する。

## 今回作る成果物
`MiniFish v0.1` Python試験機。

## 守る制約
- Chromiumのレンダリングエンジンは自作しない。
- ブラウザ操作はPlaywrightを借りる。
- AI判断部分は交換可能なPlannerとして分離する。
- APIキーなしでも外側のカラクリを試験できるようScriptedPlannerを持つ。
- 1手ごとの観測・ACTION・結果をJSONへ残す。
- 無限ループを固定ルールで止める。
- 実サイトへの破壊的な操作はv0.1試験対象外。

## 故障から逆引きした専門役
- 平賀エレキテル: Agent内部を「観測・判断・操作・状態」に分解。
- HOWTOザムライ: 1工程を observe / plan / guard / act / log に原子化。
- テクノロ爺: Chromiumは既製品、Playwrightを操縦桿として採用。
- システム工学: RunStateとEvent Logを別オブジェクト化。
- 安全工学: max_steps / max_duration / repeat loop / 404停止。
- 検品主任: deterministic demo + guard unit testsでYES/NO確認。

## カラクリ

```text
GOAL
 ↓
OBSERVE
 URL / title / accessibility snapshot / visible text
 ↓
PLAN
 ScriptedPlanner または OpenAIPlanner
 ↓
ACTION JSON
 goto / click / fill / press / back / wait / done / fail
 ↓
HARD GUARD
 loop / 404 / step / time
 ↓
PLAYWRIGHT
 Chromiumを操作
 ↓
RESULT
 ↓
EVENT LOG
 ↓
次のOBSERVE ↺
```

## TinyFish公開接続面との対応
- `goal` → MiniFish `goal`
- browser run → MiniFish `RunState`
- `runId` → MiniFish `run_id`
- `PENDING/RUNNING/COMPLETED/FAILED/CANCELLED` → 同じ考え方のstatus
- `max_steps` → `max_steps`
- `max_duration_seconds` → `max_duration_seconds`
- browser profile → Playwright `storage_state` のprofile JSON
- screenshots / html capture → `run_logs/captures`
- AgentのAI頭脳 → `Planner` interface

## v0.1で意図的に作らないもの
TinyFishのCloud Browser基盤、Stealth browser、Proxy網、Vault、Captcha/anti-bot、Makoそのもの、大規模並列、課金基盤、Webhook、Monitor、Search/Fetch製品群。

## 完成条件
1. Chromiumが立つ。
2. ページのAccessibility構造を読める。
3. Plannerが1 ACTIONを返せる。
4. click / fill / navigationが通る。
5. 結果を再観測できる。
6. run_idとstatusを持つ。
7. 全stepをJSONへ保存する。
8. 同じ操作の反復を固定ルールでSTOPできる。
9. 404反復をSTOPできる。
10. AI Plannerを差し替えられる入口が存在する。
