# 🐟📨 ChatGPT → MiniFish｜非公開原稿搬送 第1工区

## 狙い
会話中で確定した記事を、本人がコピーせずにMiniFishへ渡す。
**入力は現在この会話で実際に参照できる完成原稿だけ**。チャット全履歴への隠れたアクセスはない。
note記事の自動公開やログインとは別の工区。

## 既存部品の再利用
- ChatGPT → GitHub Issue → MiniFishの指令経路（既存）
- MiniFish Bridge Worker `bridge_worker.py`（既存）
- `minifish.note_conveyor.Article` の原稿検証／ハッシュ／下書き固定（PR #4）
- Codespacesの `.minifish/` 非公開作業領域
- noteサイト別プロファイル（PR #2・#15、実note認証は未実証）

## なぜ暗号化するのか
GitHub `Hiderock61/minifish-v01` は **public**。
GitHub Issueに元記事や会話ログをそのまま投稿すると、下書きが全世界に公開される。
この実装では送信元が記事を暗号化し、Issueに置くのは公開してもよい暗号文だけ。
受信側の秘密鍵は **Codespaceの `.minifish/` 以下だけ** に保存する。

暗号の仕組み：受信先X25519公開鍵 + 使い捨て送信鍵 → HKDF-SHA256 → AES-256-GCM。
鍵・原稿はGitHubリポジトリ、Issueコメント、Actionsログに書かない。
公開鍵だけは公開可能。なおIssueの暗号文自体はGitHubに残る。

## 初回セットアップ（Codespaces実機は未実施）
1. PR #34の開発枝 `feat/chat-note-vault-integration-v01` で **既存または新規Codespaceを起動**する。mainには未統合。
2. 既存の `.devcontainer/devcontainer.json` が `bash start_all.sh` を自動起動。
3. `CODESPACES=true` に限り `python -m minifish.chat_handoff bootstrap` を実行。
4. 秘密鍵はCodespace内 `.minifish/handoff/recipient_private.pem`（0600）、公開鍵は同じPrivateフォルダ内に作成。既存鍵は上書きしない。
5. **公開鍵だけ**を既存GitHub Issue #5へ本人アカウントで通知。公開するのはPEMのPUBLIC KEYとfingerprintだけ。原稿・Cookie・Private KEYは送らない。
6. 通知済みfingerprintをCodespaceの非公開領域で記録し、同一鍵の二重通知を回避。鍵が片方しかない、不正権限、receiptの不一致はBLOCKEDで停止。
7. ChatGPTがIssue #5の公開鍵を照合できた後、架空記事を暗号化して `[MINIFISH JOB]` Issueで送る。稼働中Workerが受信すれば status/content_keyだけ返却する。

**未実施**：今回のCodespaces本体の起動確認、実鍵の生成・Issue #5への公開鍵登録、本チャットから暗号文Issueの実送信、Workerによる本番Codespace受信。
**テスト済**：偽のCodespaces環境変数を使うローカル／CI単体試験。秘密鍵不流出・1回通知・二重通知拒否・拒否条件。
GH CLIのIssue書込み権限が無い場合、公開鍵通知はBLOCKEDで停止する。既存鍵は勝手に消さない。

CodespacesはiPhoneローカルではない。停止中はBridgeを処理できない。Codespace削除・再作成ではPrivate鍵や未発表記事が失われる可能性がある。

## 指令の形（公開GitHubには暗号文のみ）
Issueタイトル：`[MINIFISH JOB] Encrypted note intake`
Issue本文：`{"mode":"encrypted_article","envelope":{...}}`

ChatGPT側は `seal_article(article, recipient_public_pem)` で封印した後、
**利用者が指定した記事だけ**をGitHub Issue作成ツールへ渡す。
人間による本文コピペは不要。公開レポートは `status` と `content_key` だけ。

## STOP条件
- 公開鍵未登録 → STOP
- Codespace側秘密鍵なし → `AUTH_SETUP_REQUIRED`
- Issueが本人のものではない → `UNAUTHORIZED_ENCRYPTED_HANDOFF`
- 改ざんや復号失敗 → `DECRYPTION_FAILED`
- 原稿が長すぎる（UTF-8で38,000バイト超） → `ARTICLE_TOO_LARGE_FOR_GITHUB_ISSUE`
- 下書き以外のvisibility → STOP
- 同じ原稿の再配達 → `ALREADY_RECEIVED`。重複保存しない
- 受信直後の状態 → `ARTICLE_RECEIVED_NOT_POSTED`

## まだしていないこと
- 公開鍵の実登録、Codespace秘密鍵の本番生成
- ChatGPT実会話の原稿を暗号化してGitHub Issueへ渡す実E2E
- Codespace停止からの自動復帰
- noteへのログイン・下書き保存
- note→オノノケ搬送、公開・予約投稿

**この工区の成功は『原稿が安全にMiniFishの非公開受信箱へ入った』まで。**
本物のnote下書き保存・公開成功とは混同しない。

## 検品条件
- 暗号化→Codespace秘密鍵で復号→原文・タイトルが一致
- GitHubに平文なし
- 同一原稿の二重取り込みなし
- 返却コメントに原文・秘密鍵・URLの漏洩なし
- Browser/Agent/課金/API送信 0

## 2026-10-16｜自動bootstrapコードの模擬検証
- [Draft PR #34](https://github.com/Hiderock61/minifish-v01/pull/34) にCodespaces起動時の鍵生成／公開鍵だけのIssue #5通知処理を追加。mainは未変更。
- 専用の暗号化原稿・保存庫・模擬ログインCI [Actions](https://github.com/Hiderock61/minifish-v01/actions/runs/38860155819) PASS。
- 通常回帰 [Actions](https://github.com/Hiderock61/minifish-v01/actions/runs/38860155888) PASS。
- 実Codespaces鍵生成・実暗号文受信を示す証拠は **なし**。自動起動できるコードと、稼働している事実は分ける。
