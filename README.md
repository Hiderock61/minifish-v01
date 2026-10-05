# MiniFish v0.1

TinyFishを丸ごと複製するものではなく、Web Agentの中心カラクリを自分で再構成した研究用プロトタイプです。

## 何が動くか

```text
GOAL -> Observe -> Planner -> Action -> Guard -> Playwright -> Result -> Log -> Repeat
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
- `guard.py`: 数えれば分かるループを機械停止
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
