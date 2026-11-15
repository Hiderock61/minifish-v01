# 🌳 BONSaY G3-M6｜GitHubへの安全配置方式・READ ONLY確定 v0.1
2026-11-15｜明智工務店｜STATE: ISOLATED_DESIGN_PASS / NOT_DEPLOYED / ACTIONS_RUN_NOT_EXECUTED

## 目的と成果
既存M5 GitHub Actions候補（workflow_dispatch）の制限を保ったまま、mainを書き換える前に同等の無課金モデル模擬テストをGitHub Actions Python 3.11で試験する代替配置方式を確定する。コード・検査はM5から再利用し、M5原本31ファイルのSHA256を保護する。

## 1. READ ONLYで確認したGitHub現況
- Repository: Hiderock61/minifish-v01
- main current/latest examined commit: f16a39043111d0de224e793b43ab6917780a02f9（確認時点。配置直前に再確認）
- M5 Actions workflow present in main? NO (GitHub connector fetch 404)
- named M6 branch `review/bonsai-g3-m6-20261115` found? NO (search matched zero)
- existing PR #33/#40/#41/#42/#43/#44/#46 etc remain independent. This M6 does not alter or merge any PR.

## 2. Githubの成立条件と選択
| 候補 | main事前変更 | 発火条件 | 利点／制約 | 判定 |
| ---- | ---- | ---- | ---- | ---- |
| M5既存workflow_dispatch版をbranchだけに配置 | なし | manual | default branchにworkflow定義が必要。branch単独では成立しない | REJECT as branch-only |
| M6専用pull_request:[labeled] | なし | Draft PRへのownerによる限定ラベル追加 | main無変更でPRブランチからPython3.11実走可能。ただしPR作成時点で既存CIが走り得る | RECOMMEND CANDIDATE |
| branch pushでworkflow起動 | なし | push | pushで自動実行しActions消費を起こすため優先しない | DEFER |
| workflow_dispatchをmainへ登録してから--ref branch | あり | manual | 安定して手動起動可能、main登録が先に必要 | FUTURE owner decision |
| 完全ローカル実行 | なし | local pytest | GitHub Actions環境の受入証拠にはならない | M5 ALREADY PASS |

GitHubの参考：
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

## 3. 今回の候補（`bonsai-g3-m6-draft-review.yml`）
PR側ワークフローは **on.pull_request.types = [labeled]** のみ。対象ラベル名 `bonsai-g3-m6-run-approved` を owner Hiderock61 が付けた場合だけ、対象専用Draft PRのPython3.11オフライン検査を試みる。

すべて一致が必要：event labeled、ラベル正確一致、actor/PR作者 owner、Draft、同一repoのhead/base、head `review/bonsai-g3-m6-20261115`、base main、base SHA `f16a390…`。baseが変わればHOLD。トリガーはM5手動版とは独立の候補。PR作成だけではM6専用ジョブを意図的に発火させない。

重要：**PR作成時に既存main/PR側の別ワークフローが自動実行される可能性**があり、M6のジョブだけがラベル待ちでもActions計算時間ゼロとは保証できない。PRを作る前に、既存CI、Actions利用枠、セキュリティ設定を確認し、本人からGitHub変更・PR作成・実行について別途許可を受ける。Draft PRもGitHub上の作成行為でありREAD ONLYではない。

## 4. 実行内容の厳密な境界
- `m6_integrity_check.py` でM5の31ファイルをSHA256+バイト数検証（ソース・原典原文・M5ワークフローを保全）
- 既存118検査＋M6追加テストをPytestで再実行
- Python3.11で A/B 3+3世代の合成模擬公演を1回だけ実行
- 六原典のBlob SHAと総バイト数を照合
- Issueへ結果投稿・Actions artifactアップロード・OpenAI APIモデル呼出・Token count API・本物のブラウザ操作・本番外部書込をしない
- `contents: read` と `persist-credentials: false`、Secret参照なし、API SDK追加インストールなし
- Actionsランナーがcheckout/Pythonセットアップ/PyPI取得するための外部通信はあり得る。モデルAPI呼出がゼロであることと「完全ネットワーク遮断」は別。
- デフォルトブランチ以外でのCI自体の受入保証はなく、GitHub管理設定・ラベル・PR状態に依存。

## 5. 明智工務店採用判断と次工程のゲート
1. M6隔離候補・契約検査はローカルでPASSする（今回）
2. M7（**別の許可ゲート**）前にmain HEADを再読、現在開いているPR・既存CI自動発火を調べる
3. ヒデロツクが「M6専用Draft PRをGitHubに配置していい」と明示承認した場合だけ隔離ブランチとDraft PRを作成
4. 本人のさらに別のGOがあるまでラベルを付けずM6 CIは実行しない
5. 実行後はActions RUN URL、Python3.11、全テスト件数、原典SHA、A/B模擬結果、費用・課金レイヤーを個別照合
6. 合格してもBONSaY v0.1d正本化、実AI A/Bの品質判定、GitHub mainマージはしない

## HOLD / UNKNOWN
- GitHubへのbranch/PR配置：NOT_DEPLOYED
- GitHub Actions Run：ACTIONS_RUN_NOT_EXECUTED
- 実API課金・秘密アクセス：NONE
- GitHub Actions実利用枠・費用：UNKNOWN
- 既存CIの全発火一覧：UNKNOWN（配置前に調査）
- 公演の意味品質改善：UNKNOWN
- 演算原本・MiniFish main・既存PR：UNMODIFIED

**M6の成果 = 安全配置案・回帰テスト・実行ゲートを独立文書として確定したこと。実際のGitHub配置やCI実走を意味しない。**
