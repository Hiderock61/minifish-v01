# 🐟 MiniFish｜既存Codespacesへ一度だけ反映する手順

更新日：2026-10-18
作業場：既存の MiniFish Codespace `glorious disco`
ローカル作業枝：`minifish-login-33`
GitHub正本：Pull Request #33

## これは何をする装置？
PR #33 にある最新版を現在の作業枝へ早送りで取り込み、**8000番で動いている旧iPhone操縦席だけ**を終了して新版を起動する。
ログイン用ブラウザ本体（8002/6081）は新版の操縦席にあるボタンから診断・起動する。

前に済ませたCodespacesの Rebuild Container を繰り返す必要はない。デバイスの追加購入、新Codespace作成、OpenAI API設定は不要。

## 一度だけの人間操作
Codespacesのターミナルで次の1行を1回だけ実行する。

```bash
git fetch origin pull/33/head && git merge --ff-only FETCH_HEAD && python tools/refresh_codespace_ui.py
```

* `git fetch`：PR #33 の最新版を取り寄せるだけ
* `git merge --ff-only`：今の枝から順方向へ更新できる場合だけ版を進める。競合・枝の分岐ならSTOP、強制リセットなし
* `python tools/refresh_codespace_ui.py`：8000番の旧MiniFishプロセスだけ安全確認して終了・再起動。知らないプログラムが使っている場合はSTOP

`&&` は「前の命令が成功したときだけ次へ」という安全なつなぎ方。

実行前に、8000番のMiniFishで別の仕事を実行していないことを確認する。
もしエラー表示なら勝手に次の命令を試さない。
**`git reset --hard`、`git clean`、`Codespaces Delete`、`Rebuild Full` は使わない。**

## 成功したら
ターミナルに `MINIFISH_UPDATE=READY_UI_UPDATED` または `READY_UI_ALREADY_CURRENT` と出れば、8000番のiPhone操縦席を**ブラウザで再読み込み**する。

上部の「クラウドワークスの本人ログイン」欄が、8002番の実ログイン入口と6081番の画面共有を自動診断する。「MiniFishの画面を起動する」が表示された場合はそこで起動する。Private以外なら利用しない。

## PASS と HOLD
- PASS：独立GitHub Actions [RUN 39106347189](https://github.com/Hiderock61/minifish-v01/actions/runs/39106347189) = 127 PASS / 6 SKIP（安全な旧UI識別、他プロセス保護、一度だけ再起動するプログラムの模擬検査）。
- UNKNOWN：本人Codespaces内でこの命令を実際に実行できるか、実8002/6081が使えるか、iPhoneで画面を操作できるか、クラウドワークスの本人ログインを保存・再利用できるか。
- 費用：このスクリプトは新しいCodespacesやAPIを作成・起動しない。既に稼働中のCodespaces自体にはGitHub利用枠の消費がある。
- セキュリティ：本人のパスワードはChatGPT/GitHub Issueに貼らない。各サイトの2FA/外部ログインを推測・回避しない。PRはOPEN/main未統合のまま。
