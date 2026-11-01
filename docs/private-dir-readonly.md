# MiniFish｜PRIVATE_DIRECTORY_UNSAFE READ-only原因切分装置

2026-11-01 / 既存 \`accursed apparition\` のみ

## 根拠

PR #33 の \`minifish/owner_runtime.py\` の \`start_owner_desktop()\` は、\`~/.local/share/minifish\` が symlink、またはディレクトリの mode が **0700以外**なら \`PRIVATE_DIRECTORY_UNSAFE\` を返す。所有者が自分であることは当該return条件では直接確認しないが、後続の安全なファイル書込に影響し得るためREAD観測に含める。

\`start_all.sh\` の自動更新準備に \`mkdir -p "\${HOME}/.local/share/minifish"\` があり、このコマンドは0700を明示しない。修理候補 \`tools/api_bootstrap.py\` も、\`api-bootstrap\` 以下を作る際に親の \`minifish\` を0700に変更しない。**既存実機のmodeをまだ確認していないため原因は未確定**。

## 成果

\`tools/private_dir_read.py\` は filesystem の lstat **だけ**で以下の固定ラベルをREADする。

\`home\`, \`local\`, \`share\`, \`minifish\`, \`bootstrap\`, \`runtime\`, \`bootlog\`

結果：type (MISSING/DIR/FILE/SYMLINK/OTHER/INACCESSIBLE/STAT_ERROR), mode (4桁), owner_is_current (真偽値)。パス文字列、UID、ログ内容、秘密nonceを出力しない。

対象以外の \`CODESPACE_NAME\` の場合は \`HOLD_WRONG_CODESPACE\`。書込み、chmod、mkdir、Runtime POST、サーバー起動、ネットワーク呼び出し、Git checkoutなし。

## Work実機実行 (この工程では修復禁止)

1. 既存 \`accursed apparition\` だけをSTART、正しいリポジトリのVS Code Terminalに接続。旧 \`glorious disco\` を触らない。
2. 以下で独立診断branchのPython 1ファイルを \`/tmp\` へ取得し、そのGit blob SHAを比較する。

\`\`\`bash
git fetch --no-tags origin refs/heads/diag/minifish-private-dir-read-20261101
git show FETCH_HEAD:tools/private_dir_read.py > /tmp/minifish-private-dir-read.py
git hash-object /tmp/minifish-private-dir-read.py
\`\`\`

期待SHA **\`ed2d5241fde288aeab3f8603abeafca089742256\`**。不一致ならHOLD。

3. 一致時のみ以下を1回実行。

\`\`\`bash
python /tmp/minifish-private-dir-read.py
\`\`\`

4. JSONの固定項目だけ収集し、原因層を整理。

- \`ROOT_SYMLINK_MATCHES_REJECTION\`: 当該rootがsymlink。**自動置換や削除を禁止**。
- \`ROOT_MODE_MISMATCH_MATCHES_REJECTION\`: rootが実在DIRだがmode≠0700。所有者が一致している場合は最小権限修正の設計候補。**この工程ではchmodしない**。
- \`ROOT_MODE_OK_AT_READ_TIME_CAUSE_UNCONFIRMED\`: 観測時はroot mode=0700。以前の状態とは限らず、起動POSTを繰り返さずHOLD。
- \`ROOT_MISSING_AT_READ_TIME_CAUSE_UNCONFIRMED\`: rootが見つからない。以前の状態や再作成原因は未確定。
- そのほかはHOLD。

5. 最終的にGitHub管理画面から対象CodespaceをSTOP、通知を確認する。Issue #36とMiniFishのNotion正本へFACT/RESULT/UNKNOWN/NEXTを追記・読み戻す。

## 次の修理は別の承認された工程

- もし \`minifish\` が DIR、所有者一致、mode が0700以外、親パスにsymlink異常がない場合：既存ファイルに触れず、当該ディレクトリだけ \`chmod 700\` という最小変更を**別工程の候補**として検討できる。実行前にそのディレクトリを他のサービスが使っていないか確認する。
- symlink/所有者不一致/予期しない種類なら chmod や削除で直したとみなさず別途安全鑑識。
- 今回のREADで原因一致を実測しても、Runtime READYやChromium画面成功を意味しない。

## 検品

オフライン unittest 10件PASS / FAIL 0、Python構文検査PASS。**CodespaceでのREADは未実施。**