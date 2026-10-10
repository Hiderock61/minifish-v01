# 🪙 ポイ活のススメ｜MiniFish タスク起動下ごしらえ v0.1

目的: **将来のChatGPTタスクからMiniFishを呼び出せるようにするための接続契約と、安全な初回試験を固定する。**
この文書はスケジュール登録ではない。実サイトのポイ活自動化が成功した証拠でもない。

## 現在できること

- MiniFish Cloud v0.2 は `POST /api/run` で実行を受け、`run_id` を返す。
- `GET /api/run/{run_id}` で状態とイベント、ledgerを取得できる。
- `POST /api/run/{run_id}/cancel` でSTOP要求を出せる。
- `mode=poikatsu_demo` は**AI API不要の模擬アンケート**。既知回答候補を2問だけ選び、未知のQ3は空欄にする。外部送信は行わない。
- `mode=agent` は現時点ではOpenAI API設定が必要で、従量課金が発生し得る。
- Codespaces privateポートは開いている間だけ使える。24時間起動の前提にはしない。

## 最小起動契約（将来のタスク呼び出し口）

1. 実行先のMiniFishサーバーが稼働中か確認する。
2. `GET /api/_healthcheck` を呼ぶ。
3. 安全な模擬試験だけを起動する。
   ```http
   POST /api/run
   Content-Type: application/json

   {"mode":"poikatsu_demo","goal":"模擬アンケートで既知回答2件だけ入力し、未知の質問を保留する"}
   ```
4. 応答の `run_id` を保存し、`GET /api/run/{run_id}` で終了まで観測する。
5. `COMPLETED` だけでは回答の正しさは確定しない。最終ステップのARIA snapshot（checked状態）とイベントでQ1/Q2の選択・Q3未選択・送信なしを独立検証する。HTMLキャプチャは補助資料であり、動的checked状態がHTML属性へ反映されるとは限らない。
6. 実行時間・失敗・重複起動・停止理由を記録する。失敗後の再試行前に既存run_idを照合する。

## ChatGPTタスク自動起動の前提（まだ未完了）

- **常時アクセスできる実行環境**: private Codespacesの一時URLでは無人定期起動を保証できない。
- **認証**: 現状のCloud APIは外部公開向けの認証を備えていない。公開ポートにしない。将来はBearer認証等を実装し、秘密情報はSecrets管理する。
- **タスクからの呼び出し手段**: ChatGPTタスクが任意のprivate HTTP APIを直接呼べると仮定しない。利用可能な連携・認証・ネットワーク経路を実際に検証する。
- **結果回収**: 実行終了を確認し、レポートをタスク側で読める場所へ返す経路が必要。
- **本人回答DB接続**: 53項目のNotion回答DBと質問箱はまだMiniFish Cloudに直接つながっていない。
- **サイト別許可**: アンケート運営のAI利用、質問内容の共有、ブラウザ自動操作、送信の許可は別々に判定する。
- **人間承認**: WAITINGから安全にresumeするAPIは未実装。応募・送信・決済・登録を無人実行しない。

## 次の工事（順番固定）

1. `poikatsu_demo` を既存のiPhone Codespaces操縦席で1回実行し、`run_id`・HTML・EVENTを証拠として残す。
2. 外部公開せず、認証付きの起動口を設計する。
3. ChatGPTタスクまたは対応する実行器から、DEMOを1回呼べるか実機試験する。
4. 本人回答DB照合をREADとACTの間に接続する。
5. 規約上許可された実アンケートでREAD→ACT→VERIFYを1ページだけ実証する。SUBMITは別ゲート。

## 判定

- GitHubコード追加: **実装済み**
- Codespaces上の新しい `poikatsu_demo` 実行: **未検証**
- ChatGPTタスク→MiniFishの無人起動: **未接続**
- 実ポイ活の獲得報酬: **未確認**
