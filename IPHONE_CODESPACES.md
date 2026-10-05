# iPhoneからMiniFishを使う最短試験ルート

これは24時間サービス化の前に、iPhoneだけでTinyFish型の体験を成立させるための試験ルート。

## 仕組み

```text
iPhone Safari
→ GitHub Codespaces private forwarded port
→ MiniFish
→ Playwright
→ Chromium
→ Web
```

Chromebookは不要。

## 初回

1. GitHubで `Hiderock61/minifish-v01` を開く。
2. Code → Codespaces → Create codespace on main。
3. 初回セットアップ完了まで待つ。
4. Terminalで:
   ```bash
   bash start_iphone.sh
   ```
5. PORTSで8000番を開く。privateのまま使う。
6. iPhone SafariにMiniFish操縦席が出れば、まずDEMOを実行。

## AGENTモード

AGENTモードはCodespace側に次の環境変数が必要。

```text
OPENAI_API_KEY
OPENAI_MODEL
```

APIキーはGitHubリポジトリへ書かない。

設定後、START URLとGOALを入力してAGENTモードを実行する。

## 完成条件

- iPhoneで操縦席が開く
- DEMOでrun_idが出る
- STEPが進む
- COMPLETEDになる
- STOPが効く
- AGENT設定後、実WebのSTART URLを開ける
- MiniFishが1手以上ブラウザ操作する

最初の5項目で「iPhoneリモコン配線」はPROVEN。
最後の2項目で「TinyFish型の実Web Agent配線」はPROVEN。
