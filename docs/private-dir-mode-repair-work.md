# 🏯🐟🔧 MiniFish｜Private root 0755 → 0700 最小修理・Work施工書

2026-11-01 / 対象は既存 Codespace \`accursed apparition\` (ID: \`accursed-apparition-6q7jwqq5965h4rpq\`) のみ。

## FACT

前回のREAD実測で \`~/.local/share/minifish\` は所有者一致・非symlink・実ディレクトリ・mode 0755。PR #33 の \`minifish/owner_runtime.py\` は、同パスがsymlinkまたはmode≠0700なら \`PRIVATE_DIRECTORY_UNSAFE\` を返す。子 \`api-bootstrap\` は0700、親 \`.local/share\` は0755であり今回変更しない。

## 修理対象と安全設計

独立branch \`fix/minifish-private-dir-mode-20261101\` の \`tools/private_dir_mode_repair.py\` は、READ専用 \`--check\` と明示的変更 \`--apply\` を分離。

- 正確な Codespace ID、親パスの非symlink、root実DIR・owner一致・mode=0755を確認。
- 既知MiniFishサービス（8000 owner API、bridge、updater、VNC desktop、8002 controller）を \`/proc\` から識別し、異なるeffective UIDのサービスがいればHOLD。5911/6081/8002にLISTENがあればHOLD。
- 変更は \`fchmod(target_dir_fd, 0700)\` の一度だけ。親・配下ファイル・所有権・別プロセスを変更せず、inode照合と後検証を実施。
- \`--check\` はREAD専用。 \`--apply\` 後の成功固定コードは \`CHMOD_0700_VERIFIED\`。すでに0700なら \`ALREADY_0700\` / mutation0。
- UIDそのもの、プロセス引数、ログ本文、nonce、Cookie、パスは結果出力に含めない。Runtime起動POST、Chromium、外部Web呼び出し、再起動はしない。
- 限界：既知のプロセスと可視範囲のチェックは、**未知の他ユーザーサービスが当該rootを使っていないことまで保証しない**。共有利用が別途判明したら変更しない。

## 次のWork一工程

1. 既存 \`accursed apparition\` のみSTART。VS Code Terminalでリポジトリと対象IDを照合。旧 \`glorious disco\` は一切操作しない。
2. 前回の既知の作業ツリー変更 \`M start_all.sh\` / \`?? tools/api_bootstrap.py\` を保持。未知の変更は調査を深掘りせずHOLD。checkout、reset、merge、Rebuild、新Codespace作成禁止。
3. 次を実行し、スクリプトSHAを照合。

\`\`\`bash
git fetch --no-tags origin refs/heads/fix/minifish-private-dir-mode-20261101
git show FETCH_HEAD:tools/private_dir_mode_repair.py > /tmp/minifish-private-dir-mode-repair.py
git hash-object /tmp/minifish-private-dir-mode-repair.py
\`\`\`

**期待Git blob SHA:** \`fd72c21c1763198acc8817a48d8dfe0fef2e21f1\`。一致しなければHOLD。

4. READ専用で1回、状態を再照合。

\`\`\`bash
python /tmp/minifish-private-dir-mode-repair.py --check
\`\`\`

5. \`READY_TO_RESTRICT\`、\`mode_before=0755\`、\`different_owner_roles=[]\`、実機Runtimeポート不在、未知の共有依存なしを確認できた場合だけ、**次のコマンドを1回だけ**実行。

\`\`\`bash
python /tmp/minifish-private-dir-mode-repair.py --apply
\`\`\`

6. \`CHMOD_0700_VERIFIED\`、\`mode_after=0700\`、\`directory_changes=1\`、\`other_changes=0\`、\`owner_post_count=0\` であれば **PRIVATE_ROOT_MODE_REPAIRED**。それ以外はHOLDとし、再帰chmod・再実行・所有者変更・削除は禁止。別サービスのUID不一致・不明な依存があれば修理せず終了。
7. この工程では**Runtime起動POSTを再送しない**。GitHub Codespaces管理画面でSTOP、停止通知とActive消失を確認。Issue #36とNotion正本へFACT / RESULT / UNKNOWN / NEXTを追記して再読。

**修理成功とRuntime READYは別**。次便に、既存の \`owner_runtime_accept.py\` による起動POST1回とChromium実画面を検証する。

## ローカル検収

\`python -m unittest discover -s tests -p test_private_dir_mode_repair.py -v\`：**14/14 PASS**（模擬環境のみ）。Python構文検査PASS。GitHub Codespaceへの修理適用は未実施。
