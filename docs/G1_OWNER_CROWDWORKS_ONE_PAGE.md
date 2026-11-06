# 🐟 MiniFish G1｜クラウドワークス本人ログイン・最短引き渡し

## 完成状態の目標
本人は**MiniFishのプライベート画面からクラウドワークスへ自分でログインするだけ**。通常のSafariでログインしてもMiniFishのブラウザには引き継がれない。

### 工務店が準備したこと
- 既存の `PRIVATE 8002` に専用ページ `/login-ready` を追加。ボタンでMiniFishのChromiumを起動してCrowdWorksの `https://crowdworks.jp/login` を開く。
- 既存のPrivate noVNC `6081` で、人間がChromium画面を見て手でID・パスワード・2FAを操作できる構成。ChatGPTへ秘密を貼らない。
- **本人の手操作だけ**でログイン。MiniFishは認証欄を読み取らず、自動入力も押下も行わない。
- 最後に本人が「ログインできたら保存を試す」を押したときだけ、移動先が認可済みCrowdWorksでログイン画面ではないことを確認し、暗号化したブラウザ状態を保存する。
- **画面でのログイン成功と保存状態は別**。保存だけでは認証成功と判定せず「SESSION_SAVED_LOGIN_UNVERIFIED」。再起動して、本人画面が確かめられたら次工程。
- 外部のGoogleログインなどへ遷移する場合は保護のためSTOP。規約・認証障害/403/429を迂回しない。
- STOPすると未確認の状態は保存しない。実サイトへの投稿・応募・プロフィール変更は別工程。

## 実際の引渡しはまだHOLD
**実Codespacesが起動していること、現在のPRブランチでコンテナを再構築したこと、PRIVATEポート8002/6081が本人だけに見えることは未検証。**
GitHub Actionsの模擬ブラウザ試験がPASSしても、iPhoneから本物のログインページが見えるとは判定しない。

接続確認と利用枠・料金確認を済ませた**その後**、本人のPrivate Codespaces URLは次のような形になる（文字列はサンプルで、現状の実URLではない）。

`https://＜Codespace固有名＞-8002.app.github.dev/login-ready`

実URLはCodespacesのポート転送画面で確定する。推測したURLを本人用のリンクとして渡さない。

## 人間がやる最小操作（稼働確認後）
1. MiniFishの本人専用ログインページを開く。「MiniFishでログイン画面を開く」をタップ。
2. 「画面パスワードを表示」をタップして、MiniFish画面のリンクを開く。画面認証後、**クラウドワークスへ自分でログインする**。
3. 専用ページへ戻り「ログインできたら保存を試す」をタップ。完了表示を確認する。

プラットフォーム認証、2FAの実行は本人だけが担当する。保存後に認証確認ができなければG1完了としない。

## 開発・検品
- 新：`minifish/crowdworks_handoff.py` と `g1b_mock_app.py` の `/login-ready`・専用命令。
- 再利用：`PlaywrightBrowser`、`EncryptedSessionVault`、Codespaces Private 8002/6081とVNC認証。
- `tests/test_crowdworks_handoff.py`：未許可サイト停止、無人ログイン禁止、手操作後にだけ暗号化保存、STOPで保存しない、実環境がなければ起動拒否。
- **まだPROVENでない**：実CodespacesのnoVNCと起動、本人クラウドワークス画面、本人認証済み画面の再訪。完全な実用性は未判定。
- ユーザーには今日のGitHub作業、IP設定、APIキー操作、クラウドワークスのログインを要求していない。

**費用**：OpenAI API 0回。GitHub Actions/Codespacesの利用枠の消費や課金は別であり、事前確認なしにCodespacesを起動・再構築しない。
