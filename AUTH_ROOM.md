# 🐟🔐 MiniFishログイン管理室 v0.2

## 目的
各サイトのログイン状態を混ぜずに再利用し、認証が無効なら AI Planner に画面を渡す前に **WAITING / AUTH_REQUIRED** で止める。

これは **認証状態の保存と確認の基盤**。2026-10-11にCodespaces＋Chromebook＋noVNCの模擬会員ログイン保存・復元は人間の実操作で **PROVEN**。本物のポイ活サイトやiPhone Safariでのログインは未検証。

## STATE
| 部品 | 状態 |
|---|---|
| storage_state読み書き | IMPLEMENTED |
| サイト別の保存先 | IMPLEMENTED |
| 認証済み判定（明示セレクタ） | IMPLEMENTED |
| 保存なし/期限切れでWAITING | IMPLEMENTED（テスト要） |
| 認証済みの生HTML/スクリーンショットをログへ残さない | IMPLEMENTED |
| 人間がChromium内でログインするCLI | PROVEN（Codespaces/noVNC、模擬サイト） |
| 遠隔Chromiumへの手動ログイン | PROVEN（Chromebook Chrome → noVNC）。iPhone SafariはUNKNOWN |
| 実ポイ活サイトでログイン復元 | UNKNOWN |
| 定期無人起動 | HOLD |

## 台帳（アカウント秘密情報は絶対に書かない）
登録サイトの非秘密情報は `.minifish/auth_sites.json` に保存する。
`auth_sites.example.json` を参考にする。

```json
{
  "sites": [{
    "site_id": "example_site",
    "base_url": "https://example.com",
    "check_url": "https://example.com/account",
    "success_selector": "[data-testid='my-account']",
    "login_path_markers": ["/login", "/signin"]
  }]
}
```

- `site_id`: 半角英小文字で始まる識別子。アカウントID/メールアドレスではない。
- `base_url`: 対象サイトのHTTPS起点。許可するサイトだけ登録。
- `check_url`: ログイン状態の確認ページ。起点と同じオリジンに限定。
- `success_selector`: **本人ログイン時のみ可視** になる要素。ページ個別に確認する。Cookieの存在だけでは成功扱いしない。
- `login_path_markers`: 認証画面と判定するURLパス。サイトごとに調整。

状態ファイルは `.minifish/sites/<site_id>/storage.json`。public GitHubへは絶対にcommitしない。既存 `.gitignore` は `.minifish/` を無視している。

## 「それってどうやるの法©️」実行順
1. **サイトの規約確認**。ログイン状態の保持と自動ブラウザ操作が許される範囲を確認。禁止なら接続しない。
2. **サイト追加**。非秘密のURL・判定セレクタを `.minifish/auth_sites.json` に記入。パスワードとCookieは記入しない。
3. **本人ログイン**。可視のChromiumデスクトップ環境で `python auth_setup.py example_site`。本人がChromium画面でパスワード/MFA/CAPTCHAを操作。端末は共有しない。
4. **認証確認**。本人が入力終了を承認 → 明示セレクタが可視 → 保存。失敗時は保存しない。
5. **再起動**。MiniFishのAGENTモードで `site_id=example_site` と同じ登録オリジンのURLを指定。Playwrightが保存した状態を復元して認証確認。
6. **期限切れ**。確認できなければ `WAITING / AUTH_REQUIRED`。AIはログイン突破を試みず、本人再認証待ち。
7. **成功の記録**。サイトID、日時、復元可否、再認証要否のみ記録。Cookieや本人情報を証拠ログへ貼らない。

## iPhoneとCodespacesの現在の制約
`start_iphone.sh` はCodespaces内で **headless** のChromiumを起動する。
iPhone Safariでポイ活サイトにログインしても、**Codespaces側ChromiumにCookieは移らない**。
`auth_setup.py` の可視ブラウザ認証は、GUIのある信頼できる実行環境が必要。
Codespacesで手動ログインする遠隔GUI/noVNCはv0.2で実装し、Chromebookからの模擬サイト実操作で動作確認済み。
iPhone単体で完結したとは**まだ**扱わない。

## セキュリティ
- ポート8000は必ずPrivateのまま。操縦席にアプリ認証がまだないため、公開運用禁止。
- 保存ファイルは実質アカウントの鍵。owner-only権限・Git無視設定を用いる。端末自体へのアクセス管理も必要。
- 認証を使うRUNはスクリーンショット/HTMLキャプチャを作らない。イベントログの本文と入力値も伏せる。URLのクエリ/フラグメントは削除。
- **ただし** AGENT Plannerへの観測テキスト送信は残っている。秘密情報・高機密ページを対象にしない。将来は専用リダクション追加。
- アンケートの本人回答をAIに捏造させない。禁止サイトの自動回答・多重アカウント操作はしない。
- GitHub Actions実行環境は基本的に使い捨て。セッションの持続保存先ができるまでは無人の認証タスクを有効化しない。

## テスト
`PYTHONPATH=. pytest -q tests/test_auth.py`

本番サイトでの成功を記録するには、保存 → プロセス終了 → 再起動 → ログイン確認の一連の **実サイトE2E** が別途必要。


## v0.2 upgrade｜2026-10-11

### 実装済み（実機確認前）
- `start_auth_desktop.sh`: CodespacesのXvfb + x11vnc + noVNCによるiPhone Safariからの遠隔Chromium操作入口。**6080ポートは必ずPRIVATE**。
- `auth_setup.py --auto`: 本人が遠隔画面でログインした後、成功要素を自動検知して認証済みプロファイルを保存（パスワード等は表示・ログ化しない）。
- `auth_check.py SITE_ID`: AIなしで別のheadless Chromiumを起動し、認証復元の有効性を判定。
- `mock_auth_site.py`: 実アカウントを使わずiPhoneの遠隔ログインを動作確認できるlocalhost模擬サイト。
- 認証保存でIndexedDBも含める。
- `allow_actions`: 認証サイトでは初期値は `goto/back/wait`。click/fill/pressはサイト別で明示許可。Enter/Returnによるフォーム送信は人間確認。
- 通常のAgent実行では保存済み認証ファイルを**上書きしない**。状態保存はログイン成功の検証を通ったときだけ。
- テストを追加し、起動スクリプトのbash構文もCIで検査。

### 重大な制約
- **Codespacesの可視デスクトップ操作と模擬ログイン復元は、Chromebookから現地検品済み（PROVEN）。iPhone Safari実機と本物のポイ活サイトは未検証。**
- 外部実サイトは規約・操作許可・ログイン成功セレクタを個別に確認する。
- 操縦席のアプリ内独立認証、秘密ページのAI Plannerへの送信制限、無人実行は依然未解決。
- ログイン時は一時的なprivate noVNCを使い、完了後に停止する。公開転送・第三者共有は厳禁。

詳細: [IPHONE_AUTH_DESKTOP.md](./IPHONE_AUTH_DESKTOP.md)

## 現地検品 2026-10-11

**AUTH_VERIFIED → AUTH_OK → PASS** を実際のCodespaces Terminalで確認。写真を用いた本人現地検品。模擬会員サイトのみ。詳しい判定条件、検品の限界、次工程は [証拠票](docs/evidence/auth-mock-e2e-2026-10-11.md)。
