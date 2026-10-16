# 🐟 MiniFish G1b｜iPhone向け PRIVATE 画面・架空ログイン

**目的**：iPhoneから、MiniFishが開いたChromiumの画面を見て操作する入口を作る。最初の受入は架空サイトだけ。本物のランサーズ/ココナラ/CW/銀行、パスワード、2FA、応募等は絶対に扱わない。

## 実装したもの
- 既存の Codespaces Dev Container に `desktop-lite:1`（画面共有 noVNC）を追加。PRIVATEポート6080にのみ転送し、PRIVATEポート8002にMiniFish G1bのモック操縦席を置く。
- Codespace の起動時に `start_all.sh` がG1bモック操縦席を自動起動。旧8000操縦席はそのまま残す。
- iPhoneでPRIVATE 8002を開き「① 架空ログイン画面を起動」→「② ブラウザ画面を開く」→画面内の架空ログインボタンをタップ（難しければ③模擬操作ボタンも可）→「④ 暗号化して保存」→「⑤ 再起動で復元確認」。
- `g1b_mock_app.py` のPlaywrightネットワーク検問は `http://127.0.0.1:8002` **完全一致ホスト・ポート**以外を拒否。本物の外部アカウントサイトへ遷移することはできない。5分で保存せずタイムアウト。
- 保存先は `$HOME/.local/share/minifish/g1b-mock-only/`、`0600`ファイル・`0700`ディレクトリ。G1a暗号化Vaultを再利用。これは架空Cookieだけであり、実ログイン用のキー保管設備ではない。
- POST指令は同一オリジン・カスタムヘッダー確認、リクエスト/ブラウザ画面をGitHub Issue・Actions・Notionへアップロードしない。サーバー access log なし。

## 受入テスト
- `tests/test_g1b_mock_portal.py`: 外部ドメイン、別ポート、fileスキームをブラウザアクセス拒否するテスト。
- `MINIFISH_G1B_E2E=1` のCIではXvfbで見えるChromiumを開き、架空ログイン操作→暗号化保存→ブラウザ再起動→ログイン維持確認→Vault削除で再ログイン必要の動作を検証。
- 既存 pytest と旧READ契約が壊れていないことを別スイートで確認。

## Codespaces使用の条件
- Dev Container機能を追加したため、既存Codespaceでは **Rebuild Container** が必要な場合がある（自動適用とは限らない）。
- **8002と6080は必ずPrivate** に設定する。公開/組織共有への変更は禁止。公開状態なら直ちに停止。
- desktop-liteに設定された試験用VNCパスワード `G1B_MOCK_ONLY` は**公開ソースに含まれる既知の値**。本物の資格情報を扱うのに十分な認証ではない。この構成で実際のログインは**禁止**。
- Codespaces・GitHub Actionsには利用枠や料金条件がある。OpenAI API呼出は0でも、ホスティング完全無料を保証しない。
- Codespacesを停止・削除すると稼働が止まる。削除・作り直し後に保存状態が維持される保証はない。7日・30日の実セッション耐久なども未検証。

## G1bの合否
- CIで **Mock GUI/Gateway/暗号化復元** PASS → 製作と内部E2EまではPASS。
- **iPhone SafariからのnoVNC実操作** は人間の実機検品までUNKNOWN。
- **本物のサイトでのログイン維持** は次工程G1cでプライベート認証、外部接続許可、サイト規約、Cookie保護、費用、停止/失効を確認後だけ。今回達成と混同しない。

## G1cの優先課題
1. 画面共有noVNCの本番向け固有パスワードをランダム生成し、GitHubのPrivate認証と二重に守る。公開コードに埋め込まない。
2. Codespaces内部だけの本人セッション鍵作成・失効・アクセス制御と、HEADLESS作業への引継ぎ。
3. 一件の本人認可サイトだけを許可、403/429や2FA/CAPTCHAは本人操作/STOP。
4. iPhoneの1回ログイン→Worker停止・再起動→同じ本人ページをREADできるか実測。応募・公開など高影響送信はG2以降の別許可。

関連：[G1a 暗号化セッション模擬受入](G1_SESSION_MOCK.md)。
