# 🐟📝 フィッシュでノート｜MiniFish note原稿運搬ライン v0.1

## 目的
ユーザーが既に書いた原稿を機械的に運ぶ。AIに文章を勝手に書き換えさせない。TinyFishの有料自動化に勝手に切り替えない。

対象：スマホ/ChatGPT/Notionで作った記事、Z軸シリーズ、じーぴーてえーシリーズ、今日のプラグイン。
目指す経路：**スマホ→note / note→オノノケ（WordPress） / スマホ→両方**。
この工区はまず **スマホ/ChatGPTの原稿→note下書き** に専念。note→オノノケ連携はまだ未実装。

## 完成の判定を分離
- `ARTICLE_READY` = title/body/series/tags/source/destinationsを受け取り、記事のID（内容ハッシュ）を生成した。
- `MOCK_DRAFT_VERIFIED` = Chromiumで模擬記事編集フォームへ入力→「下書き保存」→保存表示を検証した。
- `AUTH_REQUIRED` = note側に実ログイン状態がない。再認証待ち。
- `DRAFT_SAVED` = 本物のnoteの編集画面で明示的な下書き保存成功表示を確認できた。
- `FAILED` = 保存できたと証明できない。公開や重複再試行は行わない。
- `PUBLISH_READY` / `PUBLISHED` = この工区では**存在しない**。公開は明示承認後の別工区。

## 自動化の部品
1. 原稿パッケージは `title`, `body`, `series`, `tags`, `magazine`, `source`, `destinations`, `visibility=draft` のJSON。
2. 記事ID `content_key` をタイトル・本文・シリーズから決定論的に作る。将来の重複登録防止の照合キー。
3. `minifish/note_conveyor.py` は既存 `PlaywrightBrowser` と `SiteAuth` を再利用する。
4. ページに存在する編集欄を **各1個** 検証してから入力。押すボタンに「下書き」「draft」と明示されなければ拒否。
5. 保存したと証明する要素が表示されなければ成功と呼ばない。投稿ボタンは操作しない。
6. note用の本番画面セレクタは現時点でUNKNOWN。勝手にDOM要素を推測せず `.minifish/note_editor.json` に **実ページで確認した内容だけ** 設定する。

## 模擬テスト（無料・ログイン不要）
CodespacesのMiniFishルートから：

```bash
python -m minifish.note_conveyor examples/note_job_example.json --mock
```

予想する結果: `MOCK_DRAFT_VERIFIED`。
GitHub Actionsもこの模擬テストを自動実行する。

## 本物のnote下書きへ移すとき
- `.minifish/auth_sites.json` に note.com をサイト別登録し、本人の同意を得た操作範囲だけ `allow_actions` を有効化する（下書き入力のための `click/fill`）。
- 初回は本人がCodespaces側のChromiumでnoteにログイン。Cookie/IndexedDBは`.minifish/sites/note_jp/storage.json`に非公開保存。
- `.minifish/note_editor.json`に編集画面URL、タイトル欄、本文欄、明示的な下書き保存ボタン、保存成功の表示用セレクタを登録する。
- `python -m minifish.note_conveyor <private-job.json> --live` で1本だけ下書き保存を試す。**現在この実サイト接続は未検証**。
- 文章はGitHubやパブリックIssueへ置かない。私有原稿はCodespacesの`.minifish/`など非公開領域に置く。

## 重要
noteには自動投稿のための一般公開された公式APIが確認できていない。今回は非公式APIを叩かず、サイトの通常のWebブラウザ操作だけを対象にする。利用規約上の迷惑行為・スパム投稿・過負荷を起こさない範囲を守る。

## 次工程
記事原稿をChatGPTから渡す入口（iPhoneの操縦席に記事フォームを追加）→ 実noteのログイン済みDOMの事実確認 → note下書き1件 → 結果とURLを非秘密台帳に保存 → note→オノノケ/両方への搬送。
