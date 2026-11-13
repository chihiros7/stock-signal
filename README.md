# stock-signal

複数ユーザーの保有株式を、利用者別のDiscordチャンネルへ取引終了後に通知するBot（**設計・開発環境構築段階**）。

- [設計ドキュメント一覧](docs/Home.md)
- [開発環境の設計](docs/Development-Environment.md)
- [実装ロードマップ](docs/Implementation-Roadmap.md)

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

現在の `stock_signal` は**環境確認用の最小プログラム**です。株価取得、CSV解析、Discord通知は未実装で、`DRY_RUN=false` は安全のため例外で停止します。

### 秘密情報とCSV

`.env.example` を参考にローカルの `.env` を作成できますが、**自動読み込みはまだ実装していません**。実運用のBotトークンや実CSVはコミットしないでください。 `.gitignore` はCSVを一律除外します。テスト用CSVもGitに置かず、必要な場合はPython内の架空データを利用します。

### 本番環境

本番はGitHub ActionsのUbuntuランナーでPythonを直接実行する予定です。DockerコンテナやCodex CLIを本番に常駐させません。ワークフローは未実装です。
