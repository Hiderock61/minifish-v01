# 🐟📱 MiniFish iPhoneログイン実験 v0.2（Codespaces + noVNC）

**ステータス：実装済み、iPhone/Safari実機での動作と本物のポイ活サイトは未検証。**

目的：iPhone SafariにサイトのCookieを保存するのではなく、**CodespacesのChromiumをiPhoneから遠隔操作して同じ環境にCookieを保存**する。

## 0. 原則
- GitHub Codespacesの **6080番ポートは必ずPRIVATE**。公開すると、ログイン画面や操作中の内容を第三者に見られる危険がある。
- noVNCのVNC内部ポート5901は127.0.0.1のみ。6080番はGitHubのprivate HTTPS転送がアクセス制御を担当する。
- 今回の簡易noVNCには独立したログイン認証はない。**Codespacesのprivate転送機構と本人のGitHubログインが必須。**
- 長時間の常時稼働、他人へのポート共有、本番金融口座等への利用はしない。
- セッション情報やパスワードをChatGPT、GitHubリポジトリ、APIのGOAL欄には貼らない。
- 手動ログインのあとVNCを停止する。

## 1. CodespacesのTerminal Aで最初の一度だけ導入

```bash
sudo apt-get update
sudo apt-get install -y xvfb x11vnc novnc websockify
python -m playwright install chromium
mkdir -p .minifish
cp auth_sites.example.json .minifish/auth_sites.json
```

実サイトを使うときは、**非秘密のサイトID、許可URL、ログイン成功時だけ見える要素**を本人の確認に基づいて設定する。

## 2. Terminal Aで画面を公開（PRIVATEのみ）

```bash
bash start_auth_desktop.sh
```

CodespacesのPORTSで **6080 / Private** を確認。Privateでなければ中止。
iPhone Safariで転送URLの `/vnc.html` を開き、Connect。遠隔のLinux画面が現れる。

## 3. まず実アカウント不要の模擬サイトで試す

Terminal B:

```bash
python mock_auth_site.py
```

Terminal C:

```bash
DISPLAY=:99 python auth_setup.py mock_site --auto --timeout 300
```

iPhone SafariのnoVNC画面にChromiumの「Login demo」が現れたら、「Sign in (no password)」をタップする。これは本人のアカウントを使わない模擬会員サイト。

Chromiumに「Demo Member」が出たら、MiniFishが自動的にログイン完了を検出する。Terminal CでEnterを押す必要はない。
認証済み要素 `#signed-in-user` が確認できた場合のみ、`.minifish/sites/mock_site/storage.json` を保存。

## 4. ブラウザ再起動後の復元チェック

Terminal C:

```bash
python auth_check.py mock_site
```

`AUTH_OK: saved session restored` と出れば、可視Chromium→保存→新しいheadless Chromium→復元の接続試験が通過。

これが失敗なら `AUTH_REQUIRED`、保存ファイルが欠落/期限切れ/ログイン成功要素が見えない等を調べる。

Terminal Aの `Ctrl-C` で **6080の遠隔ログイン画面を必ず停止**する。

## 5. 実サイトの取扱い

ポイ活サイト等の規約を確認し、自動操作が認められる範囲でのみ使う。

`auth_sites.example.json` を見て `.minifish/auth_sites.json` にサイトを追加する。
`allow_actions` は初期状態で `goto/back/wait` のみ。click/fill/pressは明示許可が必要であり、高影響の送信ボタン等は別の人間承認ゲートが止める。ただしセレクタやキーボード経由の回避を完全には防いでいないため、本番自動投稿・ポイント申請はまだ有効化しない。

ログインのたび `DISPLAY=:99 python auth_setup.py <SITE_ID> --auto --timeout 300` を使い、iPhoneの遠隔Chromium画面で本人がログイン。MFA、SMS、CAPTCHAも本人が手動処理する。

## 6. できた／まだの線引き
- ✅ GUIを遠隔転送する起動スクリプト
- ✅ ローカル模擬ログインサイト
- ✅ 人間の確認後だけ状態を保存
- ✅ 新規headless Chromiumで復元を検査するコマンド
- ✅ ログイン状態の保存にIndexedDBを含める
- ✅ AI操作の読み取り中心の既定動作、入力/クリックを許可制に
- ⏳ Codespaces実環境からiPhone Safariでログイン、復元を実行する実機検品
- ⏳ 実サイト規約・ログイン成功判定・長期保存の確認
- ⛔ 24時間無人稼働、認証付きWebサーバの公開、本番の大量自動回答


## 🔒 2026-10-15｜note本人ログインに進む前の保護（候補ブランチ）

- 遠隔デスクトップ `start_auth_desktop.sh` はCodespaces以外を原則BLOCK。例外は明示的なローカルテスト用フラグのみ。
- noVNCに独立した**一時VNCパスワード**を設定。接続画面のConnect後に求められる。Codespacesターミナルの表示から入力し、チャット・スクリーンショット・Issueには載せない。
- VNCの一時パスワードと認証ファイルは `.minifish/runtime/` に所有者限定で置き、デスクトップ終了時に消す。これはサイトのログインCookieを保存する `.minifish/sites/<site_id>/storage.json` とは別物。
- **6080番ポートのPrivate設定は依然として必須**。パスワードを追加したからPublicにしていいわけではない。
- `iphone_login_demo.sh` は一時パスワードをターミナルに表示する。模擬会員サイト自体の `Sign in (no password)` ボタンにはパスワード不要。
- 実noteでは、認証後に本人だけに見える要素を実ブラウザで確認して `.minifish/auth_sites.json` に設定する。**推測したセレクタで認証成功を宣言しない**。
- 保存→別Chromiumで復元→判定を通すまでは `AUTH_REQUIRED` 扱い。下書き保存は別の承認された試験で行う。
- Codespace削除時に保存状態が消える可能性があり、長期保存はまだ保証できない。AIによる認証済みページの取得経路も別監査。

**現在地**: VNCパスワードのコードと静的テスト追加。実Codespacesでの画面接続・実noteログイン・復元はいずれも未実施。 
