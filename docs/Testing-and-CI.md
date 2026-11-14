# 自動テスト・CI/CD計画

[← Home](Home.md) ｜ [ロードマップ](Implementation-Roadmap.md)

## 現在の実装

- Python 3.12、pytest、Ruffを使用する。開発ツールの直接依存は `requirements-dev.txt` でバージョン固定する。間接依存も含む完全なロックは今後の課題。
- push（main）・Pull Request・手動実行で `.github/workflows/ci.yml` を実行する。
- コード検査、書式検査、pytestとカバレッジ集計を行う。カバレッジ率だけを目標にしたテストは追加しない。
- pytestは標準でネットワーク接続を禁止する。テスト対象は `tests` に限定し、実CSVのある `tmp/` を収集しない。Ruffでも `tmp/` を除外する。
- CIはプロジェクトのSecretsを参照せず、`DRY_RUN=true` で動かす。GitHubトークンは `contents: read` のみにし、checkout後に認証情報を残さない。
- Actionsは検証したリリースのコミットSHAで固定する。CIから成果物・キャッシュはアップロードしない。
- 現在は環境確認、円建て評価計算、東証取引日判定、モックによる株価アダプターとメタデータ・日付・分割検証をテストしている。CSV、Discord、登録受付のテストは各機能の実装に合わせて追加する。

## 開発時の共通コマンド

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check stock_signal tests
python -m ruff format --check stock_signal tests
python -m pytest --cov --cov-report=term
```

実データでの調査は通常のテストスイートに混ぜず、Git管理外のローカル環境で行う。実データを読み込んだ状態でpytestの詳細な失敗出力やデバッガの変数を公開ログへ出さない。

## 各Phaseで追加する検証

| Phase | 自動テスト | 手動・外部連携の確認 |
| --- | --- | --- |
| 1 | DRY_RUN起動、本番モードの誤実行防止、Ruff・CI | VS CodeのF5でブレークポイント停止 |
| 2 | Decimal計算、口座別・合計、ゼロ分母、欠損・不正価格、対象日と直前取引日の一致 | 公開株価だけを使った取得元・時刻・通貨・休場日・分割の検証 |
| 3 | 完全な架空データで文字コード・前置行・列不足・口座区分を検証 | ローカルの原本で形式だけを確認し、原本や実保有値をテストへ転記しない |
| 4 | Discordの応答をモックし、本人照合・取得失敗・再試行・重複通知・削除条件を検証 | 専用チャンネルへ架空CSVで通知。削除は最後に有効化 |
| 4b | 署名不正・対象外サーバー・再送・同時登録・台帳障害・復旧 | 一般利用者の別アカウントで非公開権限を確認 |
| 5 | 休場日判定・設定検証・DRY_RUN・二重起動対策 | 手動実行を確認後、定期通知を有効化 |

## CIと本番運用・CDの分離

CIの成功だけで本番へ送信・削除・デプロイは行わない。PRのコードを本番用Secretsがある環境で実行せず、`pull_request_target` でPRのコードをcheckoutする構成も採用しない。

日次Actionsは本番の定期バッチであり、CDではない。日次処理・Workers等の本番デプロイは、次の順で追加する。

1. CIを通した変更をmainへ反映する。`Python checks` をマージ必須チェックにする設定は、CIの実動作確認後に管理者が適用する（現時点では未設定）。
2. テスト環境で架空データによる統合確認を行う。テスト環境と本番環境のBot・認証情報・保存先を分ける。
3. 日次バッチは手動DRY_RUN、テストチャンネルへの実送信、本番手動実行の順で確認し、その後に定期起動する。
4. Workersと登録台帳の採用後、検証済みmainのコミットを指定する手動デプロイを追加する。本番Secretsは本番用Environmentに限定し、承認と対象ブランチの制限を設定する。対応可否はGitHubプラン・設定を確認する。
5. 必要になった段階で本番デプロイの自動化を検討する。台帳の変更は互換性と復旧方法を事前に確認し、登録データやCSVをロールバック時に削除しない。

本番ワークフロー、Environment、デプロイ、必須チェックの設定はまだ実装・有効化していない。

## 公開情報の確認

最重要ルールはリポジトリ直下の `AGENTS.md` に従う。ステージング前・コミット前・push前の差分と履歴の確認を継続する。`.gitignore` やCI成功は秘密情報が含まれないことの保証にはならない。

秘密情報検出ツールと、CSV・秘密ファイルの誤追跡を検出するCI検査はPhase 3の実装までに追加する。現時点で自動の秘密情報検出は未導入。検知した場合は公開ログに値を再掲せず、直ちに利用者へ報告する。

公式資料：[GitHub Actionsの安全な利用](https://docs.github.com/en/actions/reference/security/secure-use)、[Ruffの設定](https://docs.astral.sh/ruff/configuration/)。
