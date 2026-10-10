# 🐟🔐 MiniFish mock-auth 現地検品報告｜2026-10-11

## 判定
**PROVEN（Codespaces + ChromebookのChrome + noVNC + 手動の模擬ログイン）**

この記録は、本人が実際にCodespacesのターミナルと遠隔Chromiumを操作し、最終画面の表示を確認した事実に基づく。チャット内の写真を目視で検品。スクリーンショットやCodespace固有の公開リンク、認証済みデータはGitHubに載せない。

## 実施したシーケンス
1. GitHub Codespaces でブランチ `feat/auth-gate-v01` を起動した。
2. ターミナルから `bash iphone_login_demo.sh` を実行した。
3. PORTSで6080番を確認し、鍵アイコン付きの `Private` として公開範囲が表示された。
4. ChromebookのChromeからCodespacesの転送URLの `/vnc.html` に接続した。
5. 遠隔のChromiumで `http://localhost:8765/login` の `Sign in (no password)` を手動で押した。
6. ターミナルの最終画面で次の表示を確認した。

```text
AUTH_VERIFIED: closing Chromium and saving state under .minifish
AUTH_OK: saved session restored
✅ PASS: human mock login saved and restored in a fresh Chromium.
```

7. `$ ` のシェルプロンプトが再表示され、実験プロセスが正常に終了したことを確認した。

## 成立した証拠
| 判定対象 | 証拠 | 結果 |
|---|---|---|
| Codespacesでのコマンド実行 | Terminal実行画面 | PROVEN |
| 6080番 PRIVATE 転送 | PORTS一覧の鍵アイコン | OBSERVED |
| noVNCとChromiumの表示 | 模擬ログインページの画面 | PROVEN |
| 本人操作による模擬ログイン | ボタン操作前後の画面 | PROVEN |
| セッション保存 | `AUTH_VERIFIED` | PROVEN |
| 別Chromiumでの復元 | `AUTH_OK` と `PASS` | PROVEN |
| 期限切れ時に停止 | GitHub Actions模擬E2Eテスト | TESTED、実サイト未試験 |
| iPhone Safariでの動作 | 今回はChromebookでの操作 | UNKNOWN |
| 実際のポイ活サイトでの保存・復元 | 実サイト未使用 | UNKNOWN |
| 再起動/再作成したCodespaceをまたぐ長期保存 | 未実施 | UNKNOWN |
| 不特定サイトの操作許可 | 規約確認未実施 | UNKNOWN |

**注意:** この成功は「MiniFishの認証インフラを模擬環境で稼働確認できた」という範囲のもの。iPhoneでの操作や実サイトへの接続、完全無人運転まで成功したことにはしない。

## セキュリティ境界
- 会員証実体（Cookie/IndexedDB storage_state）やパスワードをGitHubには保存しない。
- PORTS 6080は `PRIVATE` のままで扱う。模擬会員ログイン試験完了後は遠隔ログインデスクトップを停止する。
- 初期の認証済みサイト操作は `goto/back/wait` の閲覧中心を維持。
- 認証済み画面本文をAI Plannerに送る経路は残るため、個人情報・機密性の高い実サイトは現段階で扱わない。

## 次の1手（人間の写真往復を減らす）
1. **REPORT GATE**: 既存の `.minifish/iphone_demo_result.txt` から機械判読できる非秘密の結果票を作る。例: `run_type/mock, status/PASS, restore/OK`。ファイルはGit無視。
2. **司令塔への結果配線**: 明示的な認可のある安全な経路を設計。現在のCodespacesへChatGPTから勝手に接続できると想定しない。
3. **セキュリティ監査**: リモートVNCの独立認証、forward設定検査、PII・認証トークンの遮断、操作認可のテスト。
4. **小規模本番試験**: 規約で認められたサイト一つから、閲覧のみ・人間ログイン・復元検査で実施。

## 工程STATE
```
MiniFish v0.2
M0  コード＋CI                  PROVEN
M1  Codespaces/noVNC操作       PROVEN (Chromebook)
M2  模擬サイトのログイン復元     PROVEN (人間現地確認)
M3  iPhone Safari動作           UNKNOWN
M4  実サイトの本人ログイン       UNKNOWN
M5  認証失効と人間への引き継ぎ   TESTED in mock only
M6  定期無人運転                HOLD
```
