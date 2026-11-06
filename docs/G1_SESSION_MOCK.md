# 🐟 G1｜暗号化セッション保持・模擬ログイン受入票

## ゴール
実Webの自動化に必要な「本人が一度ログイン→Workerを再起動→同じログイン状態でREAD」の土台を、安全な内蔵模擬サイトで確かめる。

**現在の施工判定：模擬サイト専用。実サイト／iPhone本人ログインは未実証。**

## 既存品を再利用
- MiniFishの既存`PlaywrightBrowser` / `MiniFishRunner` / Playwright Chromium。
- `EncryptedSessionVault` はPlaywrightの `storage_state()` のCookie・origin stateだけを暗号化してファイル保存し、次の独立したChromiumへ復元する。
- Fernet暗号鍵は **プライベートランタイムのみ**。GitHub、Issue、CIログ、README、Git履歴には置かない。
- `.minifish/` と `*.vault` は `.gitignore` 対象。ファイル0600、保存ディレクトリ0700でない場合は拒否。
- 今までの平文`.minifish/profile.json` 自動保存は、cloud/issue workers で **無効化**。既存ファイルを無断削除はしない。

## コード受入条件と試験
1. `PYTHONPATH=. pytest -q tests/test_session_vault.py`：平文漏出なし／読込／鍵間違い／改ざん／権限／symlink／容量と形を検品。
2. `MINIFISH_G1_E2E=1 PYTHONPATH=. pytest -q tests/test_session_g1_e2e.py`：`127.0.0.1` の一時的模擬HTTP画面に、**架空のボタン**でログイン → Playwrightプロセス破棄 → 暗号化状態を新プロセスへ復元 → `AUTHORIZED_TEST_ONLY` を再確認 → vault無しでは `LOGIN_REQUIRED`。実ドメインへのHTTPアクセス無し。
3. GitHub PRのCIで成功結果を照合してから次工程へ。

## G1の未完成条件
- 本人のiPhoneでプライベートなChromium実画面へ一度ログインする経路（現在のCodespacesはheadless ChromiumとPRIVATE port 8000操縦席のみ）。
- Web Workerの存続・費用・起動方式。Codespaces消去や移転後の維持は未保証。
- 実サイトの規約・権限・URL・対象操作。ランサーズは候補で、**許可された実サイトとして追加していない**。
- 継続鍵の安全な生成・秘密保管／失効導線。テストで使用した架空鍵は再利用不可。
- ログ/結果にフォーム値や個人情報を出さない安全なフィルタ。
- 任意の実サイトログイン、CAPTCHA・2FA回避、応募・送信・課金・公開は未許可・未実装。

**次工程G1b**：実サイト接続の前にPRIVATE画面でユーザーが手作業ログインできる入口を構成し、フィールドと証拠の秘匿、キーの生存期間、明示的なサイト許可ゲートを組み込む。第三者サイトでは許可されたサイト／アカウントでのみ試験。
