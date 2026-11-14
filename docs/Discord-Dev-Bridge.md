# スマホのDiscordから開発用Codexへ指示する

[← Home](Home.md) ｜ [引き継ぎメモ](Development-Handoff.md)

> **状態：中継コードとモックテストを実装。現在のCodex会話への読み取り接続は確認済み。Discordの実送受信と、そこからの作業開始は設定完了後に確認する。** 本番の持ち株通知Bot・`/登録` とは別の開発用機能。

PC・WSL・開発コンテナ・Codexの対象会話を起動したまま利用する。コンテナ側からDiscord REST APIを定期確認するため、外部サーバーやPCへの受信用ポート開放は不要。

## 1. 開発指示用Botを作る

1. [Discord Developer Portal](https://discord.com/developers/applications)で「New Application」からアプリを作成する。
2. 「Bot」で「Public Bot」をOFFにする。他人が別のサーバーへBotを追加できないようにする設定であり、チャンネルの閲覧権限とは別。OFFで保存できない場合は「Installation → Install Link」を「None」にしてから保存する。
3. 「Requires OAuth2 Code Grant」はOFF、「Privileged Gateway Intents → Message Content Intent」はONにする。今回は公開キー・Interactions Endpoint URLは使用しない。
4. 「Bot → Reset Token」でBotトークンを発行する。チャット・Issue・Wikiへ貼らず、後述のローカル設定だけに保存する。Application IDやPublic Keyをこちらへ送る必要もない。
5. 「OAuth2 → URL Generator」でscopeの `bot` を選び、権限は「View Channels」「Read Message History」「Send Messages」を選ぶ。Administratorは付与しない。生成URLを自分のブラウザで開き、対象サーバーへ追加する。
6. **既存の専用チャンネル**の権限で、`@everyone` の閲覧を拒否し、本人とBotに閲覧・履歴を許可、Botには送信も許可する。ほかのロールやメンバーに閲覧許可がないかも確認する。サーバー管理者等によるアクセスは防げない。

スラッシュコマンドの登録やWebhook作成は不要。Botがオフライン表示でも、このREST方式ではGatewayへの接続状態を実行条件にしない。

## 2. ローカル設定

コンテナ内で実行する。

```bash
python -m pip install -r requirements-dev.txt
python -m stock_signal.dev_bridge init
```

`tmp/dev-bridge/config.json` が作成される。すでに作成済みなら上書きしない。Codexから実行すると現在の会話IDを自動設定する。

VS Codeでこのファイルを開き、次の値を入力する。設定ファイルを表示する `cat` コマンドや、トークンを引数に渡すコマンドは使用しない。

| 設定名 | 入力する内容 |
| --- | --- |
| `bot_token` | 発行したBotトークン。先頭に `Bot ` は付けない |
| `owner_user_id` | 指示を送る本人のDiscordユーザーID |
| `channel_id` | 作成済み専用チャンネルのID |
| `guild_id` | そのチャンネルがあるサーバーのID |
| `thread_id` | 自動設定されたCodex会話ID。手動で公開しない |
| `poll_seconds` | 確認間隔。初期値5秒（5〜60秒） |

Discordの「ユーザー設定 → 詳細設定 → 開発者モード」をONにすると、ユーザー・チャンネル・サーバーのメニューからそれぞれ「IDをコピー」できる。表示名やチャンネル名を入力しない。

`tmp/` 全体はGit管理外。設定・状態ファイルは所有者のみ読み書きできる権限600で保存する。認証値や実際のIDをREADME・引き継ぎメモ等へ転記しない。

## 3. 接続確認と起動

```bash
# 現在のCodex会話と作業フォルダだけを確認（Discordへは接続しない）
python -m stock_signal.dev_bridge check-codex

# Bot、専用チャンネル、履歴取得、Codexを確認（メッセージは送信しない）
python -m stock_signal.dev_bridge check

# 中継を開始。停止はCtrl+C
python -m stock_signal.dev_bridge run
```

対象チャンネルはサーバー内の通常のテキストチャンネルに限定する。DM・スレッド・公開チャンネルは対象外。同時起動はロックで防ぐ。

## 4. スマホからの操作

**中継起動後**に、専用チャンネルへ通常のメッセージとして送る。

```text
!状態
!codex 楽天CSV解析の実装を進めて、テストを実行してください
```

`!状態` はCodexの待機／実行中を定型文で返す。`!codex` はこの会話へ作業指示を送る。先に状態確認、次に短い作業を1件依頼し、実際に対象会話へ届くことを確認する。

指定した本人・チャンネルからの指示だけを受け付け、Bot・Webhookの投稿、通常の会話、添付付きの指示は実行しない。指示本文は1,800文字以内、受付は最大10件。Codexが作業中はローカルで順番待ちにする。

初回起動前の過去メッセージは実行しない。同じ設定・会話で再起動する場合は、保存済みカーソル以降の投稿と未処理キューを継続する。編集された古い投稿を新規指示として再実行しない。

返信は受付・開始・完了・失敗等の**定型文のみ**。指示の引用、モデルの返答、コード差分、コマンド出力、CSV内容、実IDはDiscordへ転送しない。詳細はCodex画面で確認する。

既存会話のモデル・権限・承認設定を引き継ぎ、中継から変更しない。必要な承認・追加質問にはPCのCodex画面で対応する。中継が要求を自動承認する機能はない。

## 再起動・エラー・会話切り替え

- 指示はローカル状態へ保存してからCodexへ送る。送信中の停止などで結果が不明になった指示は `uncertain` として保留し、自動で再送しない。PCで会話を確認し、実行されたかを判断してから状態を復旧する。
- 実行不明の指示がある間は、後続の作業開始も止める。状態ファイルを安易に削除して再実行しない。
- 通知の再送には固定nonceを使用する。Discord側の重複排除期間を超えた場合、定型通知が重複する可能性はあるが、作業を再実行する理由にはしない。
- 通信制限429は指定された時間だけ待つ。それ以外の接続エラーでは、値を出力せず状態を保持して停止する。
- コンテキストを整理しても会話IDが同じなら再設定不要。**新しい会話に切り替えた場合**は中継を停止し、未処理・実行不明の指示がないことを確認する。新しいCodex会話から `python -m stock_signal.dev_bridge retarget` を実行する。旧状態はGit管理外へ退避し、新会話では再起動後の新規投稿から受け付ける。

現実装はローカルのCodex app-server制御ソケットにWebSocketで接続する。Codex CLI 0.169.0で読み取り接続を確認済み。CLI更新時には接続とプロトコルを再検証する。Codexのデーモン・対象会話が利用できなければ、別の会話や別モデルへ勝手に切り替えず停止する。

## 検証済み／未確認

モックで本人照合、チャンネル照合、添付拒否、キュー、再起動時の重複防止、通信結果不明の保留、定型通知、秘密の例外出力抑制、会話再接続を検証した。実際のDiscord連携はトークン・IDの入力後に接続確認と試験投稿を行う。未確認の実送受信を「完了」と扱わない。

公式資料：[Bot作成](https://docs.discord.com/developers/quick-start/getting-started)、[Botの公開設定・OAuth2](https://docs.discord.com/developers/topics/oauth2)、[メッセージAPI](https://docs.discord.com/developers/resources/message)、[Codex App Server](https://learn.chatgpt.com/docs/app-server)。
