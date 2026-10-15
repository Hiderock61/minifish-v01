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

## 一度だけ必要な準備（未実施）
1. **PR #2 → PR #4 → PR #15 の依存関係に沿ってテスト・統合判断**。
2. この工区のコードを既存Codespaceへ反映する。
3. Codespaceで `python -m minifish.chat_handoff keygen` を実行する。
4. 作られた **recipient_public.pem（公開鍵のみ）** をChatGPTが読み取れる場所へ登録する。秘密鍵を渡さない。
5. 既存MiniFish Bridge Workerが実際に動いているか検証する。
6. 初回は **架空の短い公開可能なテスト原稿** のみ送る。

CodespacesはiPhoneのローカル記憶領域ではない。Codespaceの削除や再作成、ストレージ消失では秘密鍵・受信原稿が失われうる。停止中はBridgeが指令を受け取れない。

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
