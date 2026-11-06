# MiniFish G1｜File Request送信側・模擬検収

## 目的
MiniFishのPlaywrightが、自分で生成した架空の小さなUTF-8ファイルを、HTMLのファイル選択欄を使って送信できるか検証する。実Dropboxのアップロード成功を主張するものではない。

## 実装境界
- `minifish/dropbox_upload_mock.py`：127.0.0.1の一時HTTPサーバー、模擬multipartフォーム、架空ファイルの自動生成、Playwrightの`set_input_files`、検収結果。
- 受信側は固定ファイル名・固定バイト列だけ許可。書き込みを伴うHTTP POSTはこのローカル受信側 `/upload` にだけ許す。
- Playwrightの通信はlocalhost固定ポートのGET `/request` とPOST `/upload`以外拒否。実Dropbox、CrowdWorks、Codespaceの認証情報、Vaultや鍵は参照しない。
- 保存するのはテスト用一時ファイルのみ。任意のユーザーファイルや認証情報は添付できない。
- 検査はCIの既存Playwright環境でのみ。実ファイルリクエストURL・受信リンク・アップロードトークンをGitHubソース・Issues・ログへ記録しない。

## この検査で立証されること
- Chromiumのファイル選択欄へ生成済みのテストファイルをセットする操作。
- localhostの模擬受信サーバーがmultipartを受信し、固定の内容と名前を検証できること。
- ファイルを選択しないと成功判定しないこと。
- 既存MiniFishのテストが回帰しないこと。

## 未検証
- Dropbox本物のファイルリクエスト画面のJavaScript・bot対策・アップロード制限。
- 実行中の本人CodespaceからDropboxへ通信できるか。
- 本人Codespaceでの安全なリンク設定、受信確認、重複送信阻止、公開GitHubを迂回する秘匿経路。
- このチャットからCodespaceを直接遠隔操作する経路。

## NEXT
本物の送信実機検収には、PR #40/#41とこの検査の合格に加え、実Codespaceのプライベート操作経路を確立する。検証用Dropbox File Requestを公開ソースに書かない。受信箱は検証後にDropbox側で閉じる。

**結論：LOCAL送信模擬PASSが確認できても、実Dropbox送信とChatGPT受信の双方の完了は未判定。**