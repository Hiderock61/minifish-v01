# TinyFish → MiniFish 互換分解表 v0.1

目的はTinyFishのソースコードをコピーすることではなく、外から確認できる機能契約を分解し、MiniFishで同等の仕事を再構成すること。

判定:
- PROVEN: TinyFishの公開Tool surfaceから仕様を確認済み
- PARTIAL: MiniFishに骨格はあるが運用実装が未完成
- UNKNOWN: TinyFish内部の固有実装は公開Tool surfaceだけでは確定不能
- HOLD: 自家用v0.xでは後回し

| 層 | TinyFishで確認できるもの | MiniFish現在地 | 判定 |
|---|---|---|---|
| Search | public web search、geo/language/date/domain指定 | 未接続 | PROVEN / PARTIAL |
| Fetch | 最大10 URL、JS-rendered、markdown/html/json、selector、cache validator | 未接続 | PROVEN / PARTIAL |
| Monitor | search/fetchをcron実行、baseline、pause/resume/run/cancel | 未実装 | PROVEN / PARTIAL |
| Run受付 | URL + natural-language GOAL | cloud_apiでURL + GOAL | PARTIAL |
| Run lifecycle | PENDING/RUNNING/COMPLETED/FAILED/CANCELLED | 同等status + STOP | PARTIAL |
| Polling | runId → wait_for_run | run_id → GET poll | PARTIAL |
| Agent config | default/strict、max_steps、max_duration、cursor style | max_steps/max_duration | PARTIAL |
| Browser profile | lite / stealth | Chromiumのみ | PARTIAL |
| Capture | elements/snapshots/screenshots/html | ARIA/text/screenshot/HTML | PARTIAL |
| Browser action | dynamic page、click、fill、login workflow | Playwright goto/click/fill/press/back/wait | PARTIAL |
| Planner | natural-language GOALから次手決定 | OpenAIPlanner | PARTIAL |
| Guard | 内部詳細非公開 | repeat/404/max step/time | MiniFish側PROVEN |
| Browser Context Profile | setup session、cookies/storage保存、default profile | Playwright storage_state 1本 | PARTIAL |
| signed_in_sites | profile単位に記録 | 未実装 | PROVEN / PARTIAL |
| Vault | run引数にuse_vault/credential_item_ids | 未実装 | PROVEN / PARTIAL |
| Proxy | enabled + country code | 未実装 | PROVEN / PARTIAL |
| Structured output | output_schema | 未実装 | PROVEN / PARTIAL |
| Webhook | run lifecycle HTTPS webhook | 未実装 | PROVEN / PARTIAL |
| Wallet | balance/rates/topup state | 不要 | PROVEN / HOLD |
| Live browser | 実行セッションを見られる | STATE表示のみ | PARTIAL |
| Cloud browser infra | TinyFish側が提供 | remote runtime未固定 | UNKNOWN implementation |
| Stealth internals | anti-detection browser | 未実装 | UNKNOWN |
| Agent認識混合 | DOM/ARIA/vision等の正確な比率 | ARIA+text | UNKNOWN |
| Mako内部 | TinyFish固有 | OpenAIPlannerで代替 | UNKNOWN |

## Run契約

TinyFish:
```text
URL + GOAL
→ run_web_automation
→ runId
→ PENDING / RUNNING
→ wait_for_run
→ COMPLETED / FAILED / CANCELLED
```

MiniFish:
```text
START URL + GOAL
→ POST /api/run
→ run_id
→ PENDING / RUNNING
→ GET /api/run/{run_id}
→ COMPLETED / FAILED / CANCELLED
```

この契約はかなり近い。

## iPhone対応の本質

iPhone内でChromiumを動かす必要はない。

```text
iPhone
→ MiniFish Control API
→ MiniFish Runner
→ Planner
→ Playwright
→ Chromium
→ Web
```

必要なのはMiniFish本体をiPhoneから呼べるremote runtimeへ置くこと。

## 現時点で同等と呼ばない理由

Cloud Browser常時運用、named profile、Vault、Proxy、Stealth、Monitor、Search/Fetch統合、structured output、webhook、live browser viewが未完成。

一方、Agent loop、browser hand、run lifecycle、capture、guard、STOP、mobile control surfaceはMiniFish側に骨格がある。
