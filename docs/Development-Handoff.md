# 開発引き継ぎメモ

> 更新：2026-11-14。再開時は必ず `AGENTS.md` とこのメモを読み、実装・Git・CI・ローカル設定の実状態を確認する。秘密情報・実保有情報・実際の接続IDはこのメモへ記録しない。

## 目的と決定事項

- `stock-signal`：楽天／SBIのCSVを非公開Discordチャンネルへ添付し、東証営業日の引け後に評価額・前日比・損益を通知する。
- GitHubリポジトリとWikiは公開。認証情報・個人情報・実保有情報は履歴・Issue・Wiki・Actionsログ等にも一切反映しない。誤反映や疑いを検知したら直ちに利用者へ報告する。
- 利用者自身の `/登録` で専用チャンネル・権限・所有者登録を自動化する設計。Workers + D1は候補であり、導入していない。
- 日次処理はGitHub Actions。CSVと通知履歴はDiscord、登録台帳は非公開サービスに保存する計画。登録台帳の実装と本番用株価取得元は未確定。
- 利用者は初心者向けの段階的な案内を希望。秘密の値をチャットへ貼るよう求めない。区切りで本メモを更新し、コンテキストのクリアを勧める。

## 実装済み

- Phase 1：Python 3.12のDev Container、pytest・debugpy・Codex、VS Code設定。VS Code上のブレークポイント停止は手動確認が残る。
- CI：mainへのpush・PRでRuff・書式検査・ネットワーク禁止のpytestを実行。Secrets・実CSV・本番送信・自動デプロイは使わない。
- Phase 2：Decimalによる円建て評価計算、XTKS取引日判定、取得元を交換できる株価検証と開発用yfinance接続。公開銘柄と架空ポジションで実データ検証済み。カレンダー範囲は2021〜2027年。基準日以降の分割・併合は停止する。本番複数利用者向けのデータ利用条件は未解決（`Market-Data.md`）。
- 楽天CSVはローカルで構造のみ確認済み：CP932、CRLF、前置きと18列明細。実保有値はコード・テストへ転記していない。CSVパーサーは未実装。SBIの見本は未入手。
- 開発用Discord中継：`python -m stock_signal.dev_bridge`。本人・指定チャンネル限定で `!codex 作業内容` と `!状態` を受け付ける。既存のCodex会話へ接続し、返信は定型状態通知のみ。キュー、二重起動防止、再起動時の実行不明保留を実装。

## ローカルにのみ存在するもの

- 実CSV：`tmp/`。読み取りを許可されているが、値の表示・ログ・公開コンテンツへの転載は禁止。
- Discord中継設定：`tmp/dev-bridge/config.json`。現在の会話IDを自動設定して作成済み。Botトークンや各IDは利用者が入力する。実際の入力状況は再開時に値を出力せず確認する。
- 中継の状態：起動すると `tmp/dev-bridge/state.json` にカーソル・キューを保存する。`tmp/` は全体をGitから除外。設定・状態の権限は600。
- Codex認証はGit管理外のCodexホーム。トークンや設定全体を表示しない。

## Discord設定の進捗と未確認事項

- 利用者は専用チャンネルを作成済み、Developer Portalでアプリを作成済みと申告。
- Public BotはOFFで進めると案内済み。利用者の「無効」発言はこの設定を指すと解釈した。Message Content IntentはONが必要。
- 初期設定は `Discord-Dev-Bridge.md` に記載。OAuth2の `bot` scope、閲覧・履歴・送信の権限で招待する。Administrator不要。公開キー不要。
- ローカルCodexの現在の会話・作業フォルダに読み取り接続できることは確認済み。既存のモデル・承認・権限設定を中継から変更しない。
- **Discordの実送受信、DiscordからのCodex作業開始は未確認。中継の常駐実行は開始していない。** 接続設定が揃ってから `check`、`run`、スマホの `!状態`、短い `!codex` の順で確認する。
- 新会話のIDへ変更する場合は中継を停止し、未処理の指示がないことを確認して、新会話のCodexから `python -m stock_signal.dev_bridge retarget` を実行する。実行不明の指示は勝手に再送しない。

## 次に進める作業

1. 開発用Discord中継のローカル接続設定と実送受信テストを利用者と完了する。設定値は表示しない。
2. 本番ロードマップのPhase 3へ進む。秘密ファイル・CSVの誤追跡と認証情報の検出をCIへ追加する計画が残る（`Testing-and-CI.md`）。
3. 楽天CSVの形式から、完全な架空値のfixtureでパーサーを実装する。保有基準日・口座区分・数量単位・日本株以外の扱いを確定する。原本を加工してfixtureに流用しない。
4. その後、Discord日次連携、`/登録`、Actions本番運用へ進む。本番デプロイ・送信・削除はまだ有効化していない。

## 検証と反映

- 共通コマンド：`python -m ruff check stock_signal tests`、`python -m ruff format --check stock_signal tests`、`python -m pytest --cov --cov-report=term`。
- 開発用中継・会話再接続の追加後、ローカルで122件成功。実装コミット `b386a1b` の [GitHub CI](https://github.com/chihiros7/stock-signal/actions/runs/43542163428) も成功。再開時は最新コミットの結果も確認する。
- Wikiは別のGitリポジトリ。本体のdocsから `.md` を外したページリンクへ変換して同期する。`AGENTS.md` の参照は本体GitHubへのリンクに置換する。ローカル作業場所は `/tmp/stock-signal-wiki-publish`（存在しなければ再取得）。
- 本体・Wikiともにpush前に対象差分・全送信コミット・公開禁止情報の混入を確認する。Gitの著者にはGitHubの非公開用メールを使う。

## 新しい会話での再開文

「`AGENTS.md` と `docs/Development-Handoff.md` を読み、現在の実装とGitの状態を確認して続けてください。まず開発用Discord中継の接続確認を完了し、その後Phase 3の楽天CSV解析へ進めます。実CSV・認証情報は公開しないでください。」
