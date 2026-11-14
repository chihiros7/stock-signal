# stock-signal

複数ユーザーの保有株式を、利用者別のDiscordチャンネルへ取引終了後に通知するBot（**設計・開発環境構築段階**）。

- [設計ドキュメント一覧](docs/Home.md)
- [開発環境の設計](docs/Development-Environment.md)
- [実装ロードマップ](docs/Implementation-Roadmap.md)
- [自動テスト・CI/CD計画](docs/Testing-and-CI.md)
- [スマホのDiscordから開発指示](docs/Discord-Dev-Bridge.md)
- [開発引き継ぎメモ](docs/Development-Handoff.md)

## ローカル開発（Windows + WSL2 Ubuntu + Docker）

**事前準備:** WSL2 Ubuntu、Docker Desktop（WSL Integration有効）、VS Code、WSL / Dev Containers拡張。

Ubuntuターミナルで:

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/chihiros7/stock-signal.git
cd stock-signal
code .
```

VS Codeで `Ctrl+Shift+P` → **Dev Containers: Reopen in Container**。初回ビルドには時間がかかります。

コンテナ内のターミナルで:

```bash
python --version
node --version
codex --version
python -m pytest -v
python -m stock_signal
codex login --device-auth
codex
```

通常の `codex login` でブラウザ認証できる場合はそちらでも構いません。Codexのログインは本人のChatGPTアカウントで行い、トークンをチャット・Git・Dockerfileに貼り付けないでください。

Codexの認証データはDockerの名前付きボリューム `stock-signal-codex-home` に保存します。コンテナを再作成しても保持されますが、**ボリュームを削除すると消失します**。共有PCではボリュームへのアクセスにも注意してください。

### デバッグ

VS Codeの「実行とデバッグ」で **Debug stock-signal (dry run)** を選択し `F5`。テストのデバッグは **Debug pytest** を選択します。

現在の起動コマンドは**環境確認用の最小プログラム**です。円建て評価計算、東証取引日判定、開発用株価取得を実装し、架空データのテストと公開銘柄の実データで検証しています。CSV解析、Discord通知は未実装で、`DRY_RUN=false` は安全のため例外で停止します。

株価取得はyfinanceを用いた開発検証用です。複数利用者へ通知する本番用途への採用は保留しています。対象日・保有基準日・前営業日、通貨、価格欠損、分割・併合を検証します。詳細と制約は [株価取得設計](docs/Market-Data.md) を参照してください。

### 自動テスト・CI

mainへのpush・PR・手動実行で、Ruffとネットワーク接続禁止のpytestを実行します。本番の認証情報や実CSVは使用しません。

```bash
python -m ruff check stock_signal tests
python -m ruff format --check stock_signal tests
python -m pytest --cov --cov-report=term
```

CIから本番へ自動デプロイは行いません。段階的な導入計画は [自動テスト・CI/CD計画](docs/Testing-and-CI.md) を参照してください。

### 秘密情報とCSV

`.env.example` を参考にローカルの `.env` を作成できますが、**自動読み込みはまだ実装していません**。実運用のBotトークンや実CSVはコミットしないでください。 `.gitignore` はCSVを一律除外します。テスト用CSVもGitに置かず、必要な場合はPython内の架空データを利用します。

### 本番環境

本番はGitHub ActionsのUbuntuランナーでPythonを直接実行する予定です。DockerコンテナやCodex CLIを本番に常駐させません。ワークフローは未実装です。
