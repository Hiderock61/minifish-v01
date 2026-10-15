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
