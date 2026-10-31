# MiniFish｜8000起動過程のREAD専用同一RUN検収

対象：既存 Codespace \`accursed apparition\` のみ。

## 動作

\`tools/owner_8000_startup_check.py\` は起動時に \`CODESPACE_NAME\` とカレントディレクトリのリポジトリ4ファイルを照合し、合わなければ終了する。コードはREAD専用で、localhost GET以外のHTTPやPOST、外部サイトアクセス、プロセス起動・停止は行わない。

20秒の観測（0/10/20秒）で次をJSON出力する。

- Uvicorn \`cloud_api:app\` のプロセス数
- \`/proc/net/tcp*\` の8000 LISTEN
- \`127.0.0.1:8000/\` HTTP番号／接続拒否・タイムアウト等の固定分類
- \`127.0.0.1:8000/api/owner/diagnose\` HTTP番号、許可されたRuntime固定コード・can_start真偽値
- \`/tmp/minifish-api.log\` の存在・更新からの経過秒数・ファイル長・既知のエラーマーカー。ログ本文、秘密nonce、プロセスコマンド全文は出力禁止

## Work実機施工

1. 既存 \`accursed apparition\` のみSTART、VS Code Webの正しいリポジトリTerminalへ接続。
2. 一時スクリプトを以下のコマンドで取得・SHA照合（Gitの作業ツリーは変更しない）。

\`\`\`bash
git fetch --no-tags origin refs/heads/codex/minifish-owner-runtime-local-accept-20261101 && git show FETCH_HEAD:tools/owner_8000_startup_check.py > /tmp/minifish-owner-8000-startup-check.py && git hash-object /tmp/minifish-owner-8000-startup-check.py
\`\`\`

**期待blob SHA:** \`abaefcfbc40bafdf832e996fd77a200a96de81f4\`。不一致は実行せずHOLD。

3. 一致したら次を1回だけ実行。

\`\`\`bash
python /tmp/minifish-owner-8000-startup-check.py
\`\`\`

4. \`GATE\`、\`SAMPLE\` ×最大3、\`API_LOG\`、\`RESULT\` を記録。HTTP200になっても今回の工程ではPOST/Chromiumへ進まない。FAIL/HOLDでもrestart/rebuild/kill/manual startはしない。出力は固定項目のみを残す。
5. 既存CodespaceをGitHub管理画面で \`Stop codespace\`。停止通知とActive表示消失を実測。
6. GitHub Issue #36とNotion MiniFish正本へ FACT/RESULT/UNKNOWN/NEXT を記録し読み戻す。旧 \`glorious disco\` は操作禁止。

## 判定

- \`HTTP_8000_RECOVERED_OR_AVAILABLE\`: 観測中に内部トップと診断APIのHTTP 200が同一サンプルで確認された。起動遅延とは限らないため、各サンプルの差から判断。
- \`UVICORN_ABSENT_NO_LISTENER\`: 最終観測時にUvicorn不在かつ8000 LISTENなし。サーバーが一度も起動していないとは断定しない。
- \`UVICORN_OR_STARTUP_PRESENT_NO_LISTENER\`: 起動プロセスの痕跡はあるがLISTENなし。
- \`PORT_LISTENING_BUT_NO_HTTP_RESPONSE\`: 8000はLISTENしているがHTTP応答なし。
- \`HTTP_RESPONSE_OBSERVED_NOT_200_OR_DIAG_FAIL\`: HTTP応答は得られたがトップ／診断どちらかの条件不一致。
- \`HOLD_INSUFFICIENT_READ_DATA\`: 観測材料不足。

ログのマーカーは鮮度（\`age_seconds\`）と合わせて判断し、古いログから今回のエラーを断定しない。

**今回の装置は原因特定のREAD検収用。自動修理ではない。**