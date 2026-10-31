# MiniFish｜ローカル起動POST検収装置（独立実証版）

対象：PR #33を起点にした独立branchの `tools/owner_runtime_accept.py`。

## 目的と境界

Codespace **内部**から `127.0.0.1:8000` に限定して接続し、診断GETと起動POSTの実HTTP応答、Runtimeの段階、localhostの5911/6081/8002を確認する。

- **通常実行はREAD専用**。`--start` の指定時に限り、初期状態が `STOPPED` / `can_start=true` で、nonceが存在したときだけ **POSTを最大1回**送る。
- nonceは同一プロセス内の変数に保持し、**ログ・標準出力・ファイル・Issue・Notionに書かない**。HTTPレスポンスは既知の固定状態名、HTTP番号、booleanだけを表示する。
- ネットワーク先は明示的に `127.0.0.1:8000/6081/8002/5911` に限定。環境変数HTTPプロキシを無効化する。
- アカウント入力、CrowdWorksログイン、SessionVault、外部投稿・応募は一切行わない。
- **この装置ではGitHub Privateポート転送とChromiumの画面表示は証明できない**。`RUNTIME_LOCAL_PASS_CHROMIUM_UNVERIFIED` は「内部Runtimeと指定ローカルポートが動作した」に限る。`MINIFISH_BROWSER_REAL_PASS`とは別。
- GitHub Codespaceを起動・停止する機能はない。作業終了時のGitHub側STOPはWorkが別途行う。

## 作成branchから、既存CodespaceのGitを変更せず使用する

Workが既存 `accursed apparition` のVS Code Terminalを操作し、以下を実行する。旧 `glorious disco` は触れない。

```bash
git fetch --no-tags origin refs/heads/codex/minifish-owner-runtime-local-accept-20261101
git show FETCH_HEAD:tools/owner_runtime_accept.py > /tmp/minifish-owner-runtime-accept.py
python /tmp/minifish-owner-runtime-accept.py
```

最後の行は**READ専用**。Git checkout / pull / reset / merge は不要。`git fetch`はGitのリモート追跡情報だけを更新し、作業ツリーの内容を変更しない。リポジトリが不明・取得失敗なら中止し、未知のスクリプトを実行しない。

`LOCAL_8000_HOME http=200`、`GATE http=200 status=STOPPED can_start=true nonce_present=true` を観測し、安全条件が成立したときだけ、明示的な検収作業として次を1回実行する。

```bash
python /tmp/minifish-owner-runtime-accept.py --start
```

**上記コマンド自体を繰り返さない。** この制限は1プロセス当たりのPOST数を制約するものであり、別プロセスを何度も起動するとPOST回数が増えるため。実行時の確認を必須にする。

## 出力

1行1JSON。出力イベントは `RUN`、`LOCAL_8000_HOME`、`GATE`、`POST_ATTEMPT`、`POST_RESPONSE`、`RUNTIME`、`LOCAL_PORTS`、`RESULT`。

- `GATE` と `POST_RESPONSE` は `http`、`status`、`can_start`、`fixed_detail` の安全フィールドのみ。
- `nonce_present` は真偽値だけ。秘密値の文字列は絶対に出力しない。
- `POST_RESPONSE` には要求時刻、HTTP番号、POST数1が出る。
- `READY` 後に 5911 TCP、6081 `/vnc.html` HTTP、8002 `/login-ready` HTTP を検査。

検収固定結果の一例：`INITIAL_STATE_PASS_READ_ONLY`、`FAIL_8000`、`HOLD_INITIAL_STATE`、`HOLD_NONCE_MISSING`、`FAIL_START_AUTH`、`FAIL_START_HTTP`、`FAIL_PRE_VNC`、`FAIL_DIAGNOSE`、`FAIL_RUNTIME_FIXED_STATE`、`HOLD_START_TIMEOUT`、`FAIL_READY_PORTS`、`RUNTIME_LOCAL_PASS_CHROMIUM_UNVERIFIED`。

## 動作確認

```bash
python -m unittest discover -s tests -p test_owner_runtime_accept.py -v
```

ここでのユニットテストはモック。**実機POSTのPASSではない**。

## 必須の終了処理

Workは`accursed apparition`のGitHub管理画面から `Stop codespace` を操作し、GitHub停止通知を取得する。Browser Runtime自身の `STOPPED` をCodespace電源の停止と混同しない。GitHub Issue #36とMiniFish現行Notion正本には安全な固定コード・HTTP番号のみ追記する。
