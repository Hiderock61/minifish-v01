# 🏯🐟🔧 MiniFish｜noVNC秘密非表示・ローカル認証受入

**2026-11-01。実機未実行の独立診断案。**

## 既存実装で確認したこと

- 既存\`start_g1b_mock.sh\`は起動ごとに8文字VNCパスワードを \`~/.local/share/minifish/g1b-mock-only/vnc-password.txt\`（0600）へ作り、専用VNC 5911で使用する。終了時に秘密ファイルを削除する。
- \`g1b_mock_app.py\`のPRIVATE 8002 \`/login-ready\`にはnonce付き「画面パスワードを表示」ボタンがある。ボタンを押すと**ブラウザの画面DOMに秘密が現れる**。今回のWorkはこのボタンを押さず、値をチャット・スクリーンショット・ターミナル出力・Issue・Notionへ載せない。
- PRIVATE 6081 \`/vnc.html\`の既存noVNC認証UIは \`noVNC_connect_button\`, \`noVNC_password_input\`, \`noVNC_credentials_button\` の要素を持つ一般的構造。実機にインストールされた版で最終検証する。
- 前便の実機は起動POST1回・READY・5911 TCP・6081 HTTP200・8002 HTTP200・Codespace STOPを確認。ただしnoVNCパスワード未入力・Chromium未確認。

## 今回新設した診断装置

\`tools/novnc_local_accept.py\` は、MiniFish Codespace**内部**のPlaywright Chromiumで \`http://127.0.0.1:6081/vnc.html\` を開き、所有者一致・0600の既存VNC秘密を同じPythonプロセス内だけで読み、入力フォームへ渡す。パスワードはstdout/stderr、ファイル、HTTP URL、GitHub、Notion、画像へ出さない。ブラウザは診断後に閉じる。

- \`--check\`：READ専用。正確なCodespace ID、0700のPrivate親・子DIR、0600秘密ファイル、5911/6081/8002の内部接続を確認。秘密値を開かない。
- \`--connect\`：上記ゲート後、既存noVNCに1クライアント接続。手元のPlaywrightで認証ボタンを操作するが、owner RuntimeのPOST、実サイト閲覧・ログイン・応募・保存はしない。
- \`--snapshot-private\`（\`--connect\`指定時のみ）：認証後に画面Canvasが可視だった場合のみPrivate 0700ディレクトリ内へ0600の \`novnc-auth-verified.png\` を**新規1枚**保存。既に同名画像があれば上書きせずHOLD。画像は自動アップロード・GitHub保存しない。画面に他者の秘密が映る可能性があるため、Workが扱うときも外部公開禁止。
- 予期しないPlaywrightエラーは秘密値やページ本文を含む可能性があるため文字列化せず、固定\`HOLD_NOVNC_UI_OR_AUTH_UNCONFIRMED\`のみ出力する。
- 依存ライブラリ不在、noVNCのDOM差異、パス異常、再認証、画像不明は固定HOLD。再試行連打は禁止。
- \`NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE\`でも**VNC認証・Canvas表示だけ**を証明する。Chromiumが開いていること、CrowdWorks画面が見えていることは**未証明**。

## Work実機施工（既存accursed apparitionだけ）

1. 最初にGitHub Issue #36とこの文書をREAD。旧 \`glorious disco\` は触らない。
2. 既存\`accursed apparition\`をSTARTし、HEAD \`a3549bb18db802c14b24f2a47860eb6ed491ecf9\` と既知2件の未コミット変更 \`M start_all.sh\`、\`?? tools/api_bootstrap.py\` を保護する。Private root0700・所有者一致・非symlinkを再READ。Private 8000/8002/6081転送設定がPrivateなのを確認。
3. 既存 \`owner_runtime_accept.py\`（Git blob \`a4b7b1af483eeae15a6c1efc0b66d7a8c552f853\`）を既知の独立branchから\`/tmp\`に取得。通常READゲートPASS時のみ \`--start\` を**1回**。5911 TCP・6081/8002 HTTP200とRuntime READYを確認。FAILなら今回のnoVNC認証へ進まない。
4. 今回の新装置を、repo作業ツリーを変えずに\`/tmp\`に取得し、SHA一致時のみ実行。

\`\`\`bash
git fetch --no-tags origin refs/heads/diag/minifish-novnc-secretless-20261101
git show FETCH_HEAD:tools/novnc_local_accept.py > /tmp/minifish-novnc-local-accept.py
git hash-object /tmp/minifish-novnc-local-accept.py
\`\`\`

**期待Git blob SHA：`5bd38b3b29fb89d9c80a5cadfc6cf5a86e90a4df`。** 完全一致した場合だけ実行し、不一致ならHOLD。

5. まず \`python /tmp/minifish-novnc-local-accept.py --check\`。固定\`GATE_READY\`以外はHOLD。
6. PASS後、次を**1回だけ**：

\`\`\`bash
python /tmp/minifish-novnc-local-accept.py --connect --snapshot-private
\`\`\`

パスワード表示ボタン、\`cat\`、\`print\`、\`set -x\`、シェル履歴への秘密値書込み、ページのネットワークHAR/trace保存は禁止。

7. 合格なら \`NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE\` を記録。PrivateスクリーンショットをWorkが安全に確認できれば、内容は固定の画面分類だけ記録。**Chromiumが確認できなければ\`CHROMIUM_UNVERIFIED\`**。この工程はサイトログイン操作を実施しない。
8. 最後に対象CodespaceをGitHub管理画面からSTOP、GitHubの停止通知とActive消失確認。Issue #36とNotion現行正本へFACT/RESULT/UNKNOWN/NEXTを追記して読み戻す。

## コスト・境界

新Codespace/Rebuild、TinyFish、外部有料API、GitHub Actions手動起動、PR #33/main変更、Runtime重複POST、本人ログイン、SessionVault変更は実行しない。

**コードのGitHub保存だけでは実機認証のPASSにならない。** インストールされたnoVNC実版との相性と画面の実観測はUNKNOWNのまま。
