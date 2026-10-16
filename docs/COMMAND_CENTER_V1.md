# 🛰️ 司令塔ブラウザ｜MiniFish Public Commander v1

## 何が完成条件か
このChatGPTから GitHub Issue を発行すると、GitHub ActionsのChromiumで登録済み公開サイトを一度だけ観測し、URL・タイトル・短い本文・監督検査・run_idをIssueへ返し、ChatGPTがその結果を読める。

これはChatGPT **Web UIを遠隔操作する装置ではない**。ChatGPTのGitHub連携を指令管制に再利用する。OpenAI API無しでも定型的な読み取りだけできる。目的文を与えてもAIによる自律判断は起動しない。

## 使い方
ChatGPTへ次の形式で依頼するだけ。GitHubのプライベート認証操作は利用者に求めない。

> 司令塔MiniFishで「python」をREAD ONLY観測して、タイトル・本文冒頭・結果・run_id・証拠URLを報告して。書き込み・API課金なし。

ChatGPT側のGitHubコネクタは次のIssueを1件だけ新規作成する。
- タイトル: `[MINIFISH READ] <unique request label>`
- 本文 JSON: `{"mode":"read_only","url":"https://docs.python.org/3/","goal":"公開ドキュメントを読み取る"}`
- 出力はIssue内 `MINIFISH_READ_RESULT status=PASS|FAIL|BLOCKED` を読んで報告する。
- 対象は `example`, `python`, `github` の3件だけ。URLは必ず登録済みの完全一致を使用する。

## 現在の登録済みWeb
| キー | URL | 用途 |
| --- | --- | --- |
| example | https://example.com/ | 基本動作の検品 |
| python | https://docs.python.org/3/ | 公開技術文書 |
| github | https://github.com/Hiderock61/minifish-v01 | 公開リポジトリの観測 |

登録外のWeb、ログイン、フォーム送信、URLにクエリやトークンを入れることは禁止。GitHub Issue本文は公開物として扱い、秘密を入れないこと。

## 司令塔の検査とSTATE
- `PRECHECK PASS`: 指令構造、URL完全一致、費用0を検査。
- `BLOCKED`: 指令不正、登録外URLなど。ブラウザを起動しない。
- `PASS`: 実Chromiumで許可ホストのURLとタイトル/本文を観測、SupervisorGate通過。
- `FAIL`: Web取得または証拠検査に失敗。本文を取れなくても成功扱いしない。
- `run_id` / Actions URL / Issue URL / チェック項目を保存。GitHub Actionsの個別runが実行履歴の正本。
- 1Issueにつき1Actions実行。ワーカーは1RUN後に終了する。
- ハング対策: Workflow timeout 7分 / 1ページ観測 Runner timeout 40秒 / 最大1ステップ。
- 購入・投稿・応募・送信などは未実装。既存SupervisorGateのHUMAN判定は保存し、自由操作は解放しない。
- GitHub Actionsの実行中STOPや中断後RESUMEは、このv1の接続面では未実装。既存iPhone操縦席のSTOPとは区別する。
- 現時点でChatGPT以外からのIssue作成可能性はGitHub側のアクセス制御に従う（workflowでは作者ユーザー名を照合）。

## 秘密とコスト
ブラウザの認証Profileは読み込まない。保存先へCookieを書かない。OpenAIPlannerは使用しない。API呼び出し0。Web側のGETのみ。GitHub Actionsの利用枠はGitHubのアカウント設定に従うため無制限無料とは言わない。

## 未実装
任意サイト、サイト検索、自律操作、ChatGPT公式のカスタムツール登録、長期常駐、複数AI管制、実noteログイン・下書き、サイト別安全セッション移行、HUMAN承認後resume、完全なリアルタイムSTOP。これらはv1のPASSと混同しない。

## 原案
Notion正本：[司令塔ブラウザ誕生](https://app.notion.com/p/3f3c10ec598c8100b6b2f51010119bbc)
作り方：[それってどう作るの法](https://app.notion.com/p/3d9c10ec598c815cab79cdff52e9526f)

## iPhone操縦席からのPUBLIC READ
1. GitHub CodespacesでMiniFishを起動する。使い捨てのGitHub Actionsと違い、こちらは起動しているCodespace内で実行する。
2. [IPHONE_CODESPACES.md](../IPHONE_CODESPACES.md) の通り `bash start_iphone.sh` を実行。転送ポート **8000は必ずPrivate** のまま開く。
3. SafariのMiniFish画面でMODE＝**PUBLIC READ**。3サイトから選択し、START URLが自動入力される。
4. **MiniFishを動かす** → RUN STATUS、RUN ID、タイトル／本文冒頭の実観測結果を確認。STOPはブラウザ読み取り前後のチェック地点で有効であり、HTTP接続中の即時強制停止を保証しない。
5. Codespacesを削除すると内部RUN履歴が消えることがある。恒久実行記録にはGitHub Issue→Actions→結果返却経路を使う。

**注意**：iPhoneの画面テストはコード/契約テストまで。Safari実機で本人操作確認したという主張はしない。製品の全操作経路に実機PASSが必要なら別に実機試験を追加する。

## 🐟 BATCH v1｜公開3サイトを1指令で観測（AI APIなし）

ChatGPTに「MiniFishで公開3サイトをまとめてREAD ONLY検査して」と指示する。司令塔は次のGitHub Issueを**1件だけ**起票する。

- タイトルは完全一致 `[MINIFISH BATCH] PUBLIC 3`
- Issueはリポジトリ所有者の `Hiderock61` が作成する必要がある。本文の指示やURLは使わない。
- MiniFishが固定の `example` / `python` / `github` をこの順に、独立したChromiumコンテキストでそれぞれ1回だけ観測する。
- 既存の `run_public_readonly` のSupervisorGateとURL／本文の検品を再利用する。1件でも異常・予期しない観測URL・データ欠損があれば全体FAIL。
- GitHub Issueコメントへ `MINIFISH_BATCH_RESULT status=PASS|FAIL`、3件のPASS/FAILと個別run_id、Actions証拠URLを返す。
- OpenAI API 0回、ログイン0、クリック0、外部書き込み0。GitHub Actionsの利用枠は別。
- 自由巡回・リンク押下・ユーザーURL入力・他サイトへの誘導は不可。動作の安全境界は以前の固定3URLと同じ。

試験・変更記録は対応GitHub PR/Issueで追跡する。これまでの単体READ v1とは**別の新しいBATCH指令**で、既存モードは変更しない。
