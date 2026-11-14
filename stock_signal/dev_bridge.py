"""Owner-only Discord to local Codex bridge. Never forwards model output.

Run only on the development PC. All configuration and durable state live under
the Git-ignored tmp/dev-bridge directory. No inbound network listener is used.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "tmp" / "dev-bridge"
CONFIG = PRIVATE / "config.json"
STATE = PRIVATE / "state.json"
NOTICES = {
    "queued": "作業指示を受け付けました。Codexの実行が空き次第、開始します。",
    "started": "Codexで作業を開始しました。",
    "completed": "作業が完了しました。詳細はCodexの会話で確認してください。",
    "failed": "作業が完了しませんでした。Codexの会話を確認してください。",
    "uncertain": "実行結果を確認できません。重複実行を防ぐため保留しました。PCで確認してください。",
    "busy": "Codexは実行中、または操作待ちです。",
    "idle": "Codexは待機中です。",
    "invalid": "指示は添付なしの「!codex 作業内容」で送ってください。",
    "full": "受付上限に達しています。処理が終わってから送ってください。",
}


class BridgeError(ValueError):
    """Only fixed, non-sensitive messages may be used with this exception."""


class RetryLater(BridgeError):
    def __init__(self, delay):
        super().__init__("通信制限のため待機します。")
        self.delay = max(1, min(float(delay), 3600))


def snowflake(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]{17,20}", value) is not None


def private_write(path, data):
    """Atomic local write; never place prompts, tokens or IDs in Git files."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".new")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def private_read(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise BridgeError("ローカル設定・状態の権限を600にしてください。")
    return json.loads(path.read_text())


@dataclass(frozen=True, repr=False)
class Config:
    bot_token: str
    owner_user_id: str
    channel_id: str
    guild_id: str
    thread_id: str
    poll_seconds: int = 5

    @classmethod
    def load(cls, *, codex_only=False):
        data = private_read(CONFIG)
        try:
            config = cls(**data)
            uuid.UUID(config.thread_id)
        except (TypeError, ValueError, AttributeError):
            raise BridgeError(
                "ローカル設定の項目・会話IDを確認してください。"
            ) from None
        if type(config.poll_seconds) is not int or not 5 <= config.poll_seconds <= 60:
            raise BridgeError("確認間隔は5〜60秒にしてください。")
        if not codex_only:
            if not all(
                snowflake(v)
                for v in [config.owner_user_id, config.channel_id, config.guild_id]
            ):
                raise BridgeError(
                    "ローカル設定のユーザー・チャンネル・サーバーIDを入力してください。"
                )
            if not config.bot_token or any(c.isspace() for c in config.bot_token):
                raise BridgeError("ローカル設定のBotトークンを確認してください。")
        return config

    def binding(self):
        text = "|".join(
            [self.owner_user_id, self.channel_id, self.guild_id, self.thread_id]
        )
        return hashlib.sha256(text.encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Discord:
    def __init__(self, config):
        self.config = config
        self.opener = build_opener(NoRedirect())

    def request(self, path, payload=None):
        request = Request(
            "https://discord.com/api/v10" + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "Authorization": "Bot " + self.config.bot_token,
                "Content-Type": "application/json",
                "User-Agent": "stock-signal-dev-bridge/0.1",
            },
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                body = response.read(2**20 + 1)
                if len(body) > 2**20:
                    raise BridgeError("Discordの応答が大きすぎます。")
                return json.loads(body)
        except HTTPError as error:
            if error.code == 429:
                try:
                    delay = json.loads(error.read(4096)).get("retry_after", 5)
                except (ValueError, TypeError):
                    delay = 5
                raise RetryLater(delay) from None
            raise BridgeError(
                "Discord接続に失敗しました。トークンと権限をPCで確認してください。"
            ) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise BridgeError(
                "Discord通信に失敗しました。状態を保持して停止します。"
            ) from None

    def preflight(self):
        me = self.request("/users/@me")
        channel = self.request("/channels/" + self.config.channel_id)
        if (
            me.get("bot") is not True
            or me.get("id") == self.config.owner_user_id
            or channel.get("id") != self.config.channel_id
            or channel.get("guild_id") != self.config.guild_id
            or channel.get("type") != 0
        ):
            raise BridgeError("Botまたは専用テキストチャンネルの設定が一致しません。")
        everyone_private = any(
            item.get("id") == self.config.guild_id and int(item.get("deny", 0)) & 1024
            for item in channel.get("permission_overwrites", [])
        )
        if not everyone_private:
            raise BridgeError("専用チャンネルで@everyoneの閲覧を拒否してください。")

    def page(self, before=None):
        query = {"limit": 100}
        if before is not None:
            query["before"] = before
        result = self.request(
            "/channels/" + self.config.channel_id + "/messages?" + urlencode(query)
        )
        if not isinstance(result, list) or any(
            not snowflake(m.get("id")) for m in result
        ):
            raise BridgeError("Discordメッセージの形式を確認できません。")
        return result

    def since(self, cursor):
        collected = []
        before = None
        # Walk backwards so a busy channel cannot silently skip the oldest work.
        for _ in range(10):
            page = self.page(before)
            collected.extend(m for m in page if int(m["id"]) > int(cursor))
            if len(page) < 100 or any(int(m["id"]) <= int(cursor) for m in page):
                return sorted(
                    {m["id"]: m for m in collected}.values(), key=lambda m: int(m["id"])
                )
            next_before = min((m["id"] for m in page), key=int)
            if before is not None and int(next_before) >= int(before):
                break
            before = next_before
        raise BridgeError(
            "未確認の履歴が多いため保留しました。PCで状態を確認してください。"
        )

    def notify(self, key, event):
        nonce = hashlib.sha256((key + ":" + event).encode()).hexdigest()[:24]
        self.request(
            "/channels/" + self.config.channel_id + "/messages",
            {
                "content": NOTICES[event],
                "allowed_mentions": {"parse": []},
                "nonce": nonce,
                "enforce_nonce": True,
            },
        )


class Codex:
    """Read/write only a configured existing thread via the private local socket."""

    def __init__(self, config):
        self.config = config
        self.counter = 0
        self.ws = None

    def __enter__(self):
        from websockets.sync.client import unix_connect

        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        try:
            self.ws = unix_connect(
                str(home / "app-server-control/app-server-control.sock"),
                uri="ws://localhost",
                open_timeout=5,
                proxy=None,
                compression=None,
                max_size=2**20,
                legacy=True,
            )
            self.rpc(
                "initialize",
                {"clientInfo": {"name": "stock_signal_dev_bridge", "version": "0.1.0"}},
            )
            self.ws.send(json.dumps({"method": "initialized"}))
            self.status()
            return self
        except Exception:
            if self.ws is not None:
                self.ws.close()
            raise BridgeError(
                "ローカルCodexへ接続できません。会話とデーモンをPCで確認してください。"
            ) from None

    def __exit__(self, *args):
        self.ws.close()

    def rpc(self, method, params):
        self.counter += 1
        request_id = self.counter
        try:
            self.ws.send(
                json.dumps(
                    {"id": request_id, "method": method, "params": params},
                    ensure_ascii=False,
                )
            )
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                data = json.loads(
                    self.ws.recv(timeout=max(0.1, deadline - time.monotonic()))
                )
                if "method" in data:
                    # Never auto-approve tools or actions requested by the server.
                    if "id" in data:
                        self.ws.send(
                            json.dumps(
                                {
                                    "id": data["id"],
                                    "error": {
                                        "code": -32601,
                                        "message": "Use the Codex UI for interactive actions.",
                                    },
                                }
                            )
                        )
                    continue
                if data.get("id") == request_id:
                    if "error" in data:
                        raise BridgeError(
                            "Codexが要求を受け付けませんでした。PCで確認してください。"
                        )
                    return data["result"]
        except Exception:
            raise BridgeError("Codexとの通信結果を確認できません。") from None
        raise BridgeError("Codexの応答を確認できません。")

    def status(self):
        thread = self.rpc(
            "thread/read", {"threadId": self.config.thread_id, "includeTurns": False}
        )["thread"]
        if Path(thread["cwd"]).resolve() != ROOT:
            raise BridgeError("Codexの作業ディレクトリが一致しません。")
        return thread["status"]["type"]

    def start(self, prompt, job_id):
        # No model, sandbox or approval overrides: inherit the existing thread.
        result = self.rpc(
            "turn/start",
            {
                "threadId": self.config.thread_id,
                "clientUserMessageId": job_id,
                "input": [
                    {
                        "type": "text",
                        "text": "Discordの登録済み本人からの作業指示です。AGENTS.mdの最重要ルールを守ってください。\n"
                        + prompt,
                    }
                ],
            },
        )
        return result["turn"]["id"]

    def turn_status(self, turn_id):
        cursor = None
        for _ in range(10):
            params = {
                "threadId": self.config.thread_id,
                "limit": 20,
                "sortDirection": "desc",
                "itemsView": "notLoaded",
            }
            if cursor:
                params["cursor"] = cursor
            result = self.rpc("thread/turns/list", params)
            for turn in result["data"]:
                if turn["id"] == turn_id:
                    return turn["status"]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return "unknown"


class Bridge:
    def __init__(self, config, discord, codex, state_path=STATE):
        self.config, self.discord, self.codex = config, discord, codex
        self.path = state_path
        self.state = (
            private_read(state_path)
            if state_path.exists()
            else {
                "binding": config.binding(),
                "cursor": None,
                "jobs": [],
                "notices": [],
            }
        )
        if self.state.get("binding") != config.binding():
            raise BridgeError("設定と保存状態が一致しません。PCで確認してください。")
        for job in self.state["jobs"]:
            if job["status"] == "dispatching":
                job["status"] = "uncertain"
                self.notice(job["id"], "uncertain")
        self.save()

    def save(self):
        private_write(self.path, self.state)

    def notice(self, key, event):
        self.state["notices"].append([key, event])

    def authorized(self, message):
        author = message.get("author", {})
        return (
            message.get("channel_id") == self.config.channel_id
            and author.get("id") == self.config.owner_user_id
            and not author.get("bot")
            and not message.get("webhook_id")
            and message.get("type", 0) in {0, 19}
        )

    def tick(self):
        if self.state["cursor"] is None:
            page = self.discord.page()
            self.state["cursor"] = max((m["id"] for m in page), key=int, default="0")
            self.save()  # First startup deliberately ignores existing messages.
        for message in self.discord.since(self.state["cursor"]):
            if self.authorized(message):
                content = message.get("content", "").strip()
                if content == "!状態":
                    status = self.codex.status()
                    self.notice(message["id"], "idle" if status == "idle" else "busy")
                elif content == "!codex" or content.startswith("!codex "):
                    prompt = content[len("!codex") :].strip()
                    if not prompt or message.get("attachments") or len(prompt) > 1800:
                        self.notice(message["id"], "invalid")
                    elif len(self.state["jobs"]) >= 10:
                        self.notice(message["id"], "full")
                    else:
                        job_id = str(uuid.uuid4())
                        self.state["jobs"].append(
                            {"id": job_id, "prompt": prompt, "status": "queued"}
                        )
                        self.notice(job_id, "queued")
            self.state["cursor"] = message["id"]
            self.save()
        for job in self.state["jobs"]:
            if job["status"] == "running":
                status = self.codex.turn_status(job["turn_id"])
                if status in {"completed", "failed", "interrupted", "unknown"}:
                    event = (
                        "completed"
                        if status == "completed"
                        else "failed"
                        if status != "unknown"
                        else "uncertain"
                    )
                    job["status"] = event
                    self.notice(job["id"], event)
                    job.pop("prompt", None)
                    self.save()
        blocked = any(
            job["status"] in {"running", "uncertain"} for job in self.state["jobs"]
        )
        if not blocked and self.codex.status() == "idle":
            job = next((j for j in self.state["jobs"] if j["status"] == "queued"), None)
            if job is not None:
                job["status"] = "dispatching"
                self.save()  # Persist reservation BEFORE crossing the RPC boundary.
                try:
                    job["turn_id"] = self.codex.start(job["prompt"], job["id"])
                    job["status"] = "running"
                    self.notice(job["id"], "started")
                except BridgeError:
                    job["status"] = "uncertain"
                    self.notice(job["id"], "uncertain")
                self.save()
        while self.state["notices"]:
            key, event = self.state["notices"][0]
            self.discord.notify(key, event)
            self.state["notices"].pop(0)
            self.save()
        self.state["jobs"] = [
            j for j in self.state["jobs"] if j["status"] not in {"completed", "failed"}
        ]
        self.save()


@contextmanager
def locked():
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (PRIVATE / "process.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError("中継はすでに起動しています。") from None
        yield


def main():
    parser = argparse.ArgumentParser(
        description="本人専用Discord→Codex中継（開発PC用）"
    )
    parser.add_argument(
        "command", choices=["init", "retarget", "check-codex", "check", "run"]
    )
    args = parser.parse_args()
    try:
        if args.command == "init":
            if CONFIG.exists():
                raise BridgeError("ローカル設定は作成済みです。上書きしません。")
            private_write(
                CONFIG,
                {
                    "bot_token": "",
                    "owner_user_id": "",
                    "channel_id": "",
                    "guild_id": "",
                    "thread_id": os.environ.get("CODEX_THREAD_ID", ""),
                    "poll_seconds": 5,
                },
            )
            print(
                "tmp/dev-bridge/config.json を作成しました。値はチャットやGitへ貼らず、このファイルへ入力してください。"
            )
            return
        if args.command == "retarget":
            retarget()
            return
        config = Config.load(codex_only=args.command == "check-codex")
        with locked(), Codex(config) as codex:
            if args.command == "check-codex":
                print("指定したCodex会話と作業ディレクトリへの接続を確認しました。")
                return
            discord = Discord(config)
            discord.preflight()
            if args.command == "check":
                discord.page()
                print(
                    "Bot・専用チャンネル・Codex接続を確認しました。メッセージ送信はしていません。"
                )
                return
            bridge = Bridge(config, discord, codex)
            print("中継を開始します。起動前の投稿は実行しません。終了はCtrl+C。")
            while True:
                try:
                    bridge.tick()
                    time.sleep(config.poll_seconds)
                except RetryLater as error:
                    time.sleep(error.delay)
    except KeyboardInterrupt:
        print("中継を停止しました。")
    except BridgeError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print(
            "中継を停止しました。設定・接続・ローカル状態をPCで確認してください。詳細は出力しません。"
        )
        raise SystemExit(1) from None


def retarget():
    """Explicitly bind a fresh conversation, without replaying old Discord work."""
    thread_id = os.environ.get("CODEX_THREAD_ID", "")
    try:
        uuid.UUID(thread_id)
    except ValueError:
        raise BridgeError("新しいCodex会話から再接続を実行してください。") from None
    with locked():
        data = private_read(CONFIG)
        if STATE.exists() and private_read(STATE).get("jobs"):
            raise BridgeError(
                "未処理・実行不明の指示があります。PCで確認してから会話を切り替えてください。"
            )
        data["thread_id"] = thread_id
        candidate = Config(**data)
        with Codex(candidate):
            pass
        if STATE.exists():
            STATE.rename(PRIVATE / ("previous-state-" + uuid.uuid4().hex + ".json"))
        private_write(CONFIG, data)
    print(
        "現在のCodex会話へ接続先を更新しました。再起動後の新しい投稿から受け付けます。"
    )


if __name__ == "__main__":
    main()
