# BONSaY G3-M11｜実AI A/B比較・直前監査

本パッケージは**無課金のREAD ONLY検査**。実API、正式トークン計数API、GitHubへの書き込み、認証情報確認をしない。

## 実行

Python 3.11+ と pytest がある環境で：

```bash
python m11_preflight.py
python -m pytest -q test_m11_preflight.py
```

自動出力 `m11_readonly_receipt.json` は生の原典、認証情報、実AI出力を含まない。

## 固定継承（変更なし）

- `bonsai_g3_ab.py`, `bonsai_g3_transport.py`, `bonsai_g3_m1_guard.py` はM3の検収済み原本から非改変複製した。
- `pinned_six/` は六原典の固定Git Blob SHAを検証するために同梱した。非公開のAPIキーや顧客データは含めない。
- 既往のGitHub Actions G3専用検収は [#43667974332](https://github.com/Hiderock61/minifish-v01/actions/runs/43667974332)（133/133 PASS）。このパッケージ内で再現したものではない。

## 新規資料

- `M11_FINAL_READONLY_REPORT.md`：監査・費用・反証・事前品質評価基準
- `m11_preflight.py`：六原典、初回A/B入力・SHA、上限、未確認ゲートを検査
- `m11_quality_audit.py`：盲検評価票が未記入／不正ならHOLD。内容改善の自動認定はしない
- `blank_blind_review.json`：**未採点**の評価票
- `test_m11_preflight.py`：今回の無課金追加15件の検査
- `m11_readonly_receipt.json`：静的実測の機械可読結果

## HOLD

最初の実AI READY送信に進むにも、別承認、秘密の安全な設定、モデル利用権限、正確な入力トークン数、内部リトライ0の保証が必要。ChatGPTでの単なる「**あ**」は実API課金の承認と見なさない。
