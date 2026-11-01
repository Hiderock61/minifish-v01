# 🏯🐟🔍 MiniFish｜Chromium画面・ログインページの非画像検収（Work一工程）

2026-11-01。**次回実機で検収するためのオフライン設計・保存済み候補。実機未実行。**

## 既に確認済みのFACT

- 前回Work：既存\`accursed apparition\`、起動POST1回、Runtime READY、5911 TCP/6081 HTTP200/8002 HTTP200。
- Codespace内部のnoVNC認証とCanvas可視は \`NOVNC_LOCAL_AUTH_PASS_CANVAS_VISIBLE\` として実証した。Private画像はPrivate 0700ディレクトリに0600で保存、外部転送せず。Codespace最終STOP確認。
- **Chromiumウィンドウ表示とCrowdWorksログイン画面実視認はまだ未確認**。
- PR #33の既存 \`g1b_mock_app.py\` Private 8002 \`/login-ready\` には「① MiniFishでログイン画面を開く」ボタンがあり、別操作の「② 専用ブラウザの画面パスワードを表示」を押すと秘密がDOMに現れる。**②は押さない**。
- \`minifish/crowdworks_handoff.py\` は \`https://crowdworks.jp/login\` をPlaywrightのheadless=Falseで開き、許可URL・HTTP応答確認後 \`WAITING_FOR_HUMAN\` に移行。これはサイトへのナビゲーションのアプリ側証拠だが、実画像を見た証拠ではない。

## 新規装置の範囲

独立branch \`diag/minifish-chromium-window-proof-20261101\`、\`tools/chromium_gui_read.py\`：
- Python標準ライブラリだけ。READ専用で \`CODESPACE_NAME\` を対象の \`accursed-apparition-6q7jwqq5965h4rpq\` に固定。
- PR #33起点コードのGit blobをローカルで確認：\`minifish/crowdworks_handoff.py\` = \`9da6a807df46093ca42d9f60201e3657cb472470\`、\`g1b_mock_app.py\` = \`d8ae3f8de50159022876e500d29930d5422380d6\`。不一致ならHOLD。
- Private root0700・owner一致を確認。
- \`GET http://127.0.0.1:8002/g1/owner/status\` を1回。返却JSON内の \`action_nonce\` などはその場で破棄。固定許可済み \`status\` フィールドだけを利用する。
- Codespace内の \`DISPLAY=:11\` で \`xprop -root _NET_CLIENT_LIST\`、各窓の\`WM_CLASS\`と\`_NET_WM_PID\`、\`xwininfo -id ... -stats\`から **Chromium系ウィンドウ、本人UIDのChromiumプロセス、IsViewable、320x240以上のジオメトリ**をREAD照合する。OSウィンドウのタイトル、URL、PID実値、コマンド引数、ログ、画像内容は出力しない。
- \`xprop\`や\`xwininfo\`が未導入なら \`HOLD_X11_UTILITIES_MISSING\`。依存導入・Rebuildは本工程では禁止。
- 端末出力は固定コードと真偽値・検出数だけ。**画面撮影0、PNG/JPEG新規作成0、画像転送0、VNC秘密アクセス0、Runtime起動POST0、サイトへの自動POST0**。X11ウィンドウやブラウザ操作なし。
- \`CHROMIUM_WINDOW_MAPPED_LOGIN_NAVIGATION_COMPLETE_PIXELS_UNVERIFIED\` は **Chromiumの表示状態＋アプリ側サイト移動完了**を示すが、ピクセルを実視認したことは示さない。画面の本当の内容を画像抜きで厳密に証明することはできないため\`PIXELS_UNVERIFIED\`を維持。

## 次回Workで実行

1. 既存 \`accursed apparition\` のみSTART、リポジトリHEAD \`a3549bb18db802c14b24f2a47860eb6ed491ecf9\`、既知の未コミット \`M start_all.sh\` / \`?? tools/api_bootstrap.py\` を守り、PRIVATE 8000/8002/6081を再確認。旧 \`glorious disco\` は絶対操作しない。
2. 既存 \`tools/owner_runtime_accept.py\` を独立branchからSHA一致で取得し、READゲート成立時だけRuntime起動POSTを**最大1回**。READY、5911/6081/8002がPASSしなければHOLD。
3. Private 8002 \`/login-ready\` の正規ページをWorkのPrivate Browser経由で開く（本人ログインや資格情報入力は禁止）。画面の自動通信検査がPASSの場合のみ **①「MiniFishでログイン画面を開く」だけを1回**押す。②「画面パスワードを表示」、④「保存を試す」、再起動/復元は操作しない。サイトが403/429、2FA、CAPTCHA、外部送信を要求したら停止する。
4. 実際のX11/Owner API検収装置を隔離取得、Git blob SHA固定一致時のみ実行。

\`\`\`bash
git fetch --no-tags origin refs/heads/diag/minifish-chromium-window-proof-20261101
git show FETCH_HEAD:tools/chromium_gui_read.py > /tmp/minifish-chromium-gui-read.py
git hash-object /tmp/minifish-chromium-gui-read.py
\`\`\`

**期待SHA： \`f8eae7e286f01f56ea24cf2a64db62ba4280e057\`**。

5. 事前に[モック試験](../tests/test_chromium_gui_read.py)13項目をローカルで実行、全件PASSを必須とする。試験コードは同じbranchの\`tests/test_chromium_gui_read.py\`を隔離ディレクトリへ取り、相対位置 \`../tools/chromium_gui_read.py\` を保つ。Github上で保存しただけではQA PASSではない。
6. \`python /tmp/minifish-chromium-gui-read.py\` を**1回**実行。結果に \`WAITING_FOR_HUMAN\`、\`chromium_pid_owner_verified=true\`、\`chromium_mapped_viewable=true\` がある場合、OS上のChromium窓表示とアプリ側ナビゲーションをPASSとする。
7. 出力にはスクリーンショット、Webページ内容、title、nonce、PID、Cookie、VNCパスワードを載せない。**今回は既存Private画像も新規スクリーンショットも開かず転送しない**。したがって\`CROWDWORKS_PIXEL_VISUAL_PASS\`とは宣言しない。
8. GitHub管理画面から既存CodespaceをSTOP、停止通知・Active消失を確認。GitHub Issue #36 / Notion正本へFACT/RESULT/UNKNOWN/NEXTを記録して読み戻す。

## より厳密な「目視」をするなら

ユーザー本人がGitHub認証済みのPRIVATE 6081のライブnoVNC画面を**自身の端末で**見る方法はある。ただしこれはCodespaceからユーザー端末へ画面データを送るため、文字どおりの「画像を外に出さない」とは両立しない。**本工程では採用しない。**

現行設計の合格は \`CHROMIUM_WINDOW_MAPPED_LOGIN_NAVIGATION_COMPLETE_PIXELS_UNVERIFIED\`。秘密を外へ出さない条件と画面の「目視」の厳密な意味を混同しない。
