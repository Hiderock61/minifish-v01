# 🌳 BONSaY G3-M5｜隔離・手動Actions候補 v0.1
2026-11-15｜明智工務店｜現在地: ISOLATED_CANDIDATE（未配備）

## 結論
既存MiniFishのG1/G2は改造しない。GitHub Actions向けにG3の**101件の既存回帰テスト・六原典照合・A/Bの3+3世代の無課金模擬公演**をまとめて実行する、手動起動だけの候補を隔離設計した。これはAIの意味品質やT0航路改善効果の実証ではない。

- `g3/`：M3の凍結済みPythonソース・101テスト・六原典（Git Blob SHA固定）。保存内容改変なし。
- `m5_offline_runner.py`：六原典実バイト照合 → 費用検問付きA/B模擬4回×2 → 一時的な模擬原文削除 → 最小の公開安全サマリー保存。実AIクライアント／SDKを渡す経路なし。
- `m5_summary_check.py`：期待した機械結果のみを許可。Python 3.11 実行済みかも確認。
- `test_m5_contract.py`：GitHub Actions構成の不意な課金・公開・トリガー混入を回帰検査。
- `.github/workflows/bonsai-g3-m5-offline-candidate.yml`：候補のみ。`workflow_dispatch` 手動起動・read-only権限・owner限定・Python 3.11・pytestのみ導入。公開Issue書込み、artifactアップロード、Secrets利用、OpenAI SDKの導入・モデルAPI通信は行わない。

## 実施済みと未実施を分離
**実施済み（局所環境）**：101既往テスト＋新規M5テスト17件、合計118/118 PASS、六原典の現物SHA検査、A/B模擬公演の同一T0・独立セッション・共通費用検問。実行時のPythonは3.13.5。受け入れ合否は `evidence/` 内。

**未実施（HOLD）**：GitHub Actions上のPython 3.11での実RUN、ワークフローのGitHubへの反映、実AI接続と請求、第三者実用レビュー、T0航路の意味品質の改善効果。

注意：`workflow_dispatch` はGitHub上で原則**デフォルトブランチにワークフローが存在している必要**がある。隔離ブランチへファイルを置くだけで手動起動できるとは保証しない。本人承認後に登録・起動方式を別契約で決定すること。**本パッケージの作成はその承認を意味しない。**

## 実行コマンド（ローカル再検査）
Python 3.11/3.13, pytest==9.0.2 が使える環境で、パッケージのrootから：

```bash
python -m pytest -q g3 test_m5_contract.py
BONSAI_G3_OFFLINE_MODE=offline_mock python m5_offline_runner.py --out m5_public_summary.json
```

上記ローカル実行は `--require-python311` を付けない。Actions候補では必ず同オプションを指定してPython 3.11実行を強制する。`m5_summary_check.py` はPython 3.11上でできたサマリーにのみPASSを出す。

## セキュリティと費用の境界
- GitHubへまだ配備していない。workflowは `on: workflow_dispatch` 以外のイベントを持たない。
- GitHub secretsを参照しない。OpenAI API/Token count API/ブラウザ操作は **0**。
- 外部通信はActionsが checkout や `pip` で実行環境を構成する際に必要になり得る。モデル呼出をしないことと完全オフラインは異なる。
- Actions利用分はGitHubのアカウント枠・プラン条件によって課金され得る。**『無課金試験』は『有料AI APIなし』の意味であってActions計算資源の無料保証ではない。**
- 生の模擬会話履歴は一時ディレクトリ内に限定し終了時に消去。公開ログ・artifactに出すのは安全な短い結果だけ。
- `run_checked_pair`の意味判定は `UNKNOWN`、マーカー整合は意味品質の証拠ではない。

## 最小の次工程（M6案）
必要ならowner承認の隔離ブランチでCI実行計画を固定し、**既存mainを変更する前に**差分・発火条件・Actions利用枠・デフォルトブランチ制約を独立監査する。実RUN実行・mainへの反映・課金は明示許可があって初めて行う。

**判定**：M5構成設計 + ローカル受入PASS ／ Python3.11 GitHub Actions実行 UNKNOWN ／ 実AI A/B HOLD。
