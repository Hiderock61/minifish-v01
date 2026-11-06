# G1｜本人CodespaceからDropboxへ送る最小装置（独立検査）

## T0・今回の任務
2026-11-07。既存MiniFishのPlaywrightにより、本人Codespaceから、Dropbox File Requestに**固定の架空テキスト**を一度だけ送れるか検証する。既に本人iPhone→実Dropbox→ChatGPT Dropbox connectorのLIST/READは53バイトの架空テキストでPASS済み。PR #42はlocalhost模擬POSTがPASS。今回は**その送信側の本番向けゲートを施工しただけで、まだ実Codespaceの本番送信は実施していない**。

## ファイルと安全設計
- `minifish/dropbox_owner_sender.py` は本人Codespace専用。公開Issue/Bridgeから起動するコードは追加しない。
- `CODESPACE_NAME` あり、`MINIFISH_OWNER_DROPBOX_PROBE_APPROVED=1` かつpytest実行外でない限り、実Dropbox送信は禁止。
- 受取URLは本人Codespace実行環境の **`MINIFISH_PRIVATE_DROPBOX_REQUEST_URL`** からのみ取得。URL・ID・Cookie・ヘッダー・ページ内容はソース、README、GitHub Actionsログ、issueコメント、結果JSONへ書かない。
- 許可するURLは `https://www.dropbox.com/request/<opaque-id>` 型だけ。userinfo、port、fragment、query、HTTP、外部ドメインは拒否。
- **新しい空のChromiumコンテキスト**で実行。既存CrowdWorksの暗号化Vault/鍵、保存済みブラウザコンテキスト、個人ファイルは読まない。Service Workers無効、スクリーンショット/HTMLログなし。
- 添付できるのはソースに固定した `minifish_owner_probe_20261107.txt` と固定の架空テキストだけ。ファイルは一時フォルダに生成し使用後破棄する。
- ネットワーク送信先はDropbox関連ドメインに限定し、外部送信先を遮断。想定外のJS・UI・API・権限要求時はSTOP。
- マーカーを本人環境の `~/.local/share/minifish/owner-dropbox-probe/upload-one-shot-v1.attempted` に0600で最初に作り、成功不明でも同じ試験の自動再送を許さない。ディレクトリ0700、シンボリックリンク拒否。
- エラー・タイムアウトを受けたら固定ステータスだけ返す。Playwrightの生エラーはログへ出さない。
- `SUBMISSION_ATTEMPTED_UNVERIFIED` は**Dropbox受信PASSではない**。受信箱を認証済みDropbox connectorで別READしてファイル名・バイト数・内容一致を確かめたときだけ実送信PASSを宣言する。

## 非公開URLの取扱い
現在の受取窓口はユーザーが発行したもの。過去の旧URLが公開GitHubの参照外コミットへ残った事故を再発させない。今回**実際の新URLはGitHub内のどのファイルにも書かない**。実行時に使う秘密の設定と本人許可は、接続済みのプライベート実行環境でのみ行う。公開IssuesやGitHub Actionsの`env`へ値を埋め込まない。ファイルリクエストURLは送信専用のBearer capabilityで、知る人は匿名で投稿できる。

## 検証工程
1. PR #43の模擬送信試験をGitHub CIで実行。ドメインガード、未承認拒否、二重送信拒否、非公開文字列不出力を確認する。
2. **ここでは本人既存Codespaceを触らない。** 残存する未コミット変更・Vault・鍵を保護したまま、レビュー済みの変更だけを隔離worktreeに配置する実機運用計画を立てる。
3. 本人許可と非公開URL入力を、安全なCodespace操作インターフェースで実施できることを確認する。URLを本人にチャットへ貼らせない。
4. 1回だけ自動アップロードを行う。Dropboxから1件受信したか、ファイル内容・サイズ一致を別の接続で確かめる。
5. Dropboxのファイルリクエストを終了。接続されたDropbox APIでは終了操作不可。本人Dropbox UIから閉じる。必要ならテストファイルを本人承認後に削除する。

## 残課題・HOLD
このチャットに現在、既存Codespace `accursed apparition` のプロセスへコマンド実行する権限がない。GitHubソース編集とCodespace実機操作は別物。PRがCI PASSしても、ユーザーのCodespaceから**本物のDropboxへ送信したことにはならない**。Dropboxの実WebフォームのDOMに依存するため、実機でSTOPする可能性がある。HTTP 403/429や想定外の画面を回避しない。

## 保護
PR #43はPR #42のテストブランチをbaseとする独立下書き。PR #42/#41/#40/#33、main、現行Codespace、Vault、鍵、未コミット変更は変更せず、無断マージしない。
