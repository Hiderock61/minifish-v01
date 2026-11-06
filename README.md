# MiniFish v0.1

TinyFishを丸ごと複製するものではなく、Web Agentの中心カラクリを自分で再構成した研究用プロトタイプです。

## 何が動くか

```text
GOAL -> Observe -> Planner -> Supervisor Gate -> Action -> Playwright -> Result -> Log -> Repeat
```

観測にはURL、title、PlaywrightのARIA snapshot、画面本文を使用します。操作はPlaywrightで `goto / click / fill / press / back / wait` を実行します。

## まずAIなしで壊れないか確認

Python 3.11+ 推奨です。

```bash
git clone https://github.com/Hiderock61/minifish-v01.git
cd minifish-v01
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python demo_run.py
```

成功すると `run_logs/demo_run.json` と step ごとのHTML/スクリーンショットが残ります。

システムChromiumを明示的に使いたい場合だけ `MINIFISH_CHROMIUM_PATH` を設定できます。通常はPlaywrightが管理するChromiumを使います。

テスト:

```bash
PYTHONPATH=. pytest -q
```

## AIのタレを入れる

現在のOpenAI APIでは新規統合はResponses APIが中心です。`OpenAIPlanner` は `OPENAI_API_KEY` と `OPENAI_MODEL` を受け取り、観測とGOALから1手だけJSONで返す構成です。

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL='<APIで利用可能なモデル名>'
python ai_run.py 'https://example.com' 'Pricingページを見つけて最安プラン名を確認する'
```

APIキーや利用可能モデルはリポジトリへ保存しないでください。

## カラクリの部品

- `models.py`: GOAL / Run / Observation / Action / Event
- `browser.py`: Chromiumを動かす手足
- `planner.py`: 次の一手を決める頭脳。AIなし版とOpenAI版を分離
- `guard.py`: PLAN→ACTION間のSupervisor Gate。repeat / 404 / URL ping-pong / HUMAN GATEを決定論で判定
- `runner.py`: 観測→判断→操作→再観測を回す心臓

## これはまだTinyFishと同じではない

TinyFishの公開接続面にはCloud Browser、Stealth、Proxy、Browser Context Profile、Vault、capture、structured output、run lifecycleなどがあります。MiniFish v0.1はその中の「Agent loop + browser hand + run state + capture」の最小骨格だけを再現しています。


## iPhoneから使う

MiniFish v0.2では、iPhone自体でChromiumを動かすのではなく、remote runtime上のMiniFishをSafariから操縦する。

最短の試験経路はGitHub Codespaces。

1. このrepositoryをCodespaceで開く。
2. `bash start_iphone.sh` を実行。
3. forwardされた8000番ポートをprivateのまま開く。
4. iPhone Safariから操縦席を開く。
5. まずDEMOで `run_id → RUNNING → COMPLETED` を確認。
6. `OPENAI_API_KEY` と `OPENAI_MODEL` をremote runtime側に設定するとAGENTモードが使える。

詳細: `IPHONE_CODESPACES.md`

TinyFishとの差分表: `TINYFISH_DECOMPOSITION.md`

> APIキー、Cookie、ブラウザProfileはrepositoryへcommitしない。


## Supervisor Gate v0.1

MiniFishを作る目的はTinyFishの完全コピーではなく、Agentの **PLAN → ACTION** 間を自分たちで所有し、実行前に司令塔を挟めるようにすること。

現在の固定ルール:

- 同じURLで同じACTIONが3回目 -> `STOP`
- 404を2回観測 -> `STOP`
- URLが A→B→A→B -> `REPLAN`
- 購入・契約・削除・応募・支払・公開などの高影響クリック -> `HUMAN`
- 同じGOAL / MODE / START URLの生存RUN -> APIが409で重複RUNを拒否

`HUMAN` ではブラウザ操作を実行せず `WAITING` にする。人間承認後のresume APIは次段階。

### 現在のゴール

**MiniFishを「動く魚」から「司令塔付きWeb作業員」にする。**

次の大きな段階は、Supervisor Gateの判定をSTATE LEDGER / HUMAN FACTへ接続し、ChatGPTから実Web仕事を任せても迷子・二重実行・高影響操作の暴走を防げる状態にすること。


## 🛰️ 司令塔ブラウザ｜ChatGPTと接続する無料のREAD ONLY経路

ChatGPTのGitHub連携 → Issue指令 → GitHub Actions → MiniFish監督付きChromium → 結果コメントの実運用経路です。認証不要の登録済み公開ページだけを読みます。OpenAI API課金、Webサイトへの投稿、ログイン操作は行いません。

iPhoneだけの使用方法・許可サイト・受入条件・未実装機能は [司令塔操縦ガイド](docs/COMMAND_CENTER_V1.md) に明記。

## 🔐 G1｜ログイン保持の土台（模擬サイト段階）

従来の平文セッション自動保存をcloud/Issue Workerで止め、既存PlaywrightBrowserへ暗号化Session Vaultを追加しました。模擬サイトの「ログイン→ブラウザ破棄→新ブラウザでログイン保持」を専用CIで受入検査します。本物のランサーズ／ココナラ等のログインはまだ許可・実証していません。

工程、秘密・費用の境界、次の本人ログイン入口は [G1 セッション保持・模擬ログイン受入票](docs/G1_SESSION_MOCK.md) を参照。OpenAI API不要、実サイトへの外部書込みなし。
