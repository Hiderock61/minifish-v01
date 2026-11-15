# 🌳 BONSaY G3-M12｜READY 1発話の実AI接続直前ゲート v0.1

**2026-11-15｜LOCAL / NO NETWORK / NO API CHARGE / NO GITHUB WRITE**

## 結論

M11の六原典・費用台帳・品質評価仕様を変更せず、最初の**A条件のREADYのみ**を将来の実API接続に載せるための隔離ゲートを実装した。

- **今回の検収**: M11既往ローカル15検査 + M12新規31検査 = **46/46 PASS**（この隔離環境ではPython 3.13.5）。GitHub ActionsでのG3 133/133 / Python 3.11.18 PASSは既往証拠として継承し、M12のPython 3.11検収を行ったとは主張しない。
- **実API送信**: **0**、公式カウンタAPI通信 **0**。秘密鍵取得 **0**、GitHub変更 **0**。
- **実AIのREADY品質・T0航路改善**: **UNKNOWN**。M12の成功パスは偽SDKだけで検収した。実SDK・アカウントの利用権限・残高・ネットワークは未確認。

## 今回新しく固定したカラクリ

1. `OwnerPermit` の**公式計数承認・有料READY承認・プロジェクト権限確認・現在料金確認**がすべてTRUEで、別途**二つの明示的ランタイム許可**がある場合だけ実行入口を通る。普段は全FALSE。通常の「あ」はこれらの承認ではない。
2. SDKは **`max_retries=0`** を指定して生成し、実際のクライアント属性も0であることを検査。既存の注入済みクライアントではこの証明を省略しない。実SDK固有の内部実装がさらに再試行をしないことは、まだ実SDKで検証していない。
3. 六原典を**6個のGit Blob SHA、合計76,809 UTF-8バイト**で検証。`_instructions` とA条件の `START_PROMPT` から、M11で記録したものと**完全一致する初回入力SHA**を生成する。外部URLをモデルが読んだ証拠とは扱わない。
4. `responses.input_tokens.count(model=...,input=...)` で公式計数。返された件数をリクエストの全体SHA256に拘束し、モデルに送る実リクエストにすり替わりがあればSTOP。カウントAPIの実通信も別許可が必要。
5. `SpendLedger` を再利用して、**50,000入力トークン以下／出力512以下／1モデル要求のみ／推定上限$0.01**を送信前に確かめる。公式Standard短文脈の参考単価に基づき、最大50k入力×512出力の試算は**$0.005256**。**請求書上の絶対上限ではない**。モデル価格、処理tier、地域追加料金・利用可能残高は本番直前に別途照合する。
6. 外部通信より前に、所有者のみアクセス可能な非公開ディレクトリ（0700）に**永続的な一回限りマーカー**（0600）を排他的に生成する。計数失敗・通信切断・異常応答・実行途中停止でも**削除せず再送禁止**。同一非公開ディレクトリを全試行で継続利用することが必要で、複数ホスト・複数ディレクトリを跨いだグローバル排他は未実証。
7. 返答本文をGitHub Issue・PR・ログへ出さず、非公開の0600新規ファイルに保存。公開戻り値はハッシュ・状態・推定費用のみ。返答がREADYでなければHOLD。READYを返せても**世代1/T0「あ」「あ」へ進まない**。

## 実行方法（今日許されるのはオフラインだけ）

```
python m12_ready_gate.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p no:cacheprovider -q test_m11_preflight.py test_m12_ready_gate.py
```

CLIはオフライン固定で、認証情報を読まず、APIライブラリを読み込まず、公式計数・モデル通信もしない。ローカルテストは偽SDKを注入し、計数→予算→モデル呼出→機密保存の順序を検査する。保存されたテスト用回答はpytest一時領域に置き、完成ZIPには含めない。

**M12には自動ライブ実行CLIはない。** 本番には独立した実行許可、秘密鍵を晒さない供給経路、当日の料金・アカウント残高・モデルアクセス検査、個別の誤送信レビューが必要。実際のOpenAI SDKでの零リトライ検証とPython 3.11実機動作も未実証。

## 継承する固定事項

- M11の17ファイルは原本ZIPからそのままコピー。SHA256検証は別添 `M12_SOURCE_INTEGRITY.json` を参照。
- PR #47 DRAFT・未マージのまま。G3 Actions 133件PASSを変更・再実行していない。
- T0: 「AIで仕事が速くできるようになると、人間の仕事の価値はどう変わる？」
- 条件A/B：六原典同一、BはT0航路チェックを付加する候補。今回のREADYは**Aのみ**。

### 残る技術的な境界

- `responses.create` に `service_tier` を指定しない場合、API仕様上はプロジェクト設定に従う `auto`。そのため**実行プロジェクトがStandard（default）であり、地域加算等がないことの独立確認**を省いてはならない。設定が確認できなければ `OwnerPermit` を発行しない。料金をコードの固定値だけで保証したとは扱わない。
- `max_retries=0` はSDKが公開する再試行設定をゼロにする。独自ネットワークプロキシ・インフラの内部再送や外部請求額まで数学的に保証するものではない。
- one-shotマーカーは**同一ディレクトリ内での重複送信防止**。ホストが異なる場合に共通ロック・共有永続ストレージを使わなければ、全環境横断の一回限りは立証できない。
- 実AIレスポンスは `store=False` でリクエストするが、サービス提供側のログや保持ポリシー全体をゼロ保存とみなさない。

## 次の一手（別工程）

M12コードを隔離のままPython 3.11で独立検収するか、オフラインでSDK契約との整合テストを追加する。その後、**正式な有料1回許可があった場合のみ**公式計数・READY 1発話へ進む。M12が通っても8回のA/Bを自動許可しない。

## 公式参照

- SDKの `max_retries=0`：https://github.com/openai/openai-python/blob/main/README.md
- Responses公式計数：https://github.com/openai/openai-python/blob/main/src/openai/resources/responses/input_tokens.py
- トークン計数ガイド：https://developers.openai.com/api/docs/guides/token-counting
- GPT-6 Luna料金：https://developers.openai.com/api/docs/models/gpt-6-luna
