"""Only fictional IDs, credentials and instructions; no real Discord traffic."""

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError

import pytest

from stock_signal import dev_bridge as dev


def sid(n):
    return str(10**17 + n)


@pytest.fixture
def config():
    return dev.Config(
        "fictional-token",
        sid(1),
        sid(2),
        sid(3),
        "00000000-0000-4000-8000-000000000000",
    )


@pytest.fixture
def setup(config, tmp_path):
    discord = Mock()
    discord.page.return_value = [{"id": sid(10)}]
    discord.since.return_value = []
    codex = Mock()
    codex.status.return_value = "idle"
    codex.start.return_value = "fake-turn"
    codex.turn_status.return_value = "inProgress"
    bridge = dev.Bridge(config, discord, codex, tmp_path / "state.json")
    return bridge, discord, codex


def message(config, **kwargs):
    result = {
        "id": sid(11),
        "channel_id": config.channel_id,
        "author": {"id": config.owner_user_id},
        "type": 0,
        "content": "!codex 架空の変更を確認する",
    }
    result.update(kwargs)
    return result


def test_first_start_does_not_replay_history(setup):
    bridge, discord, codex = setup
    bridge.tick()
    assert bridge.state["cursor"] == sid(10)
    discord.since.assert_called_once_with(sid(10))
    codex.start.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"author": {"id": sid(9)}},
        {"channel_id": sid(9)},
        {"author": {"id": sid(1), "bot": True}},
        {"webhook_id": sid(9)},
        {"type": 7},
    ],
)
def test_only_configured_owner_and_channel_can_submit(setup, config, change):
    bridge, discord, codex = setup
    discord.since.return_value = [message(config, **change)]
    bridge.tick()
    codex.start.assert_not_called()
    discord.notify.assert_not_called()
    assert bridge.state["cursor"] == sid(11)


def test_owner_work_is_reserved_before_dispatch_and_never_echoed(setup, config):
    bridge, discord, codex = setup
    prompt = "PRIVATE-FICTIONAL-MARKER"
    discord.since.return_value = [message(config, content="!codex " + prompt)]

    def start(text, job_id):
        state = dev.private_read(bridge.path)
        assert state["cursor"] == sid(11)
        assert state["jobs"][0]["status"] == "dispatching"
        assert text == prompt
        return "fake-turn"

    codex.start.side_effect = start
    bridge.tick()
    codex.start.assert_called_once()
    assert bridge.state["jobs"][0]["status"] == "running"
    assert "PRIVATE" not in str(discord.notify.call_args_list)
    assert bridge.path.stat().st_mode & 0o077 == 0


def test_busy_thread_queues_then_runs_once_when_idle(setup, config):
    bridge, discord, codex = setup
    codex.status.return_value = "active"
    discord.since.return_value = [message(config)]
    bridge.tick()
    codex.start.assert_not_called()
    discord.since.return_value = []
    codex.status.return_value = "idle"
    bridge.tick()
    bridge.tick()
    codex.start.assert_called_once()


@pytest.mark.parametrize(
    "content,attachment",
    [("!codex", []), ("!codex test", [{"id": "fake"}]), ("!codex " + "x" * 1801, [])],
)
def test_empty_oversize_and_attachment_instructions_are_not_executed(
    setup, config, content, attachment
):
    bridge, discord, codex = setup
    discord.since.return_value = [
        message(config, content=content, attachments=attachment)
    ]
    bridge.tick()
    codex.start.assert_not_called()
    assert discord.notify.call_args.args[1] == "invalid"


def test_plain_chat_does_not_execute_anything(setup, config):
    bridge, discord, codex = setup
    discord.since.return_value = [message(config, content="普通の会話")]
    bridge.tick()
    codex.start.assert_not_called()


def test_restart_during_dispatch_holds_instead_of_replaying(setup, config):
    bridge, discord, codex = setup
    bridge.state["cursor"] = sid(10)
    bridge.state["jobs"] = [
        {"id": "fake-job", "status": "dispatching", "prompt": "fictional"}
    ]
    bridge.save()
    restarted = dev.Bridge(config, discord, codex, bridge.path)
    restarted.tick()
    codex.start.assert_not_called()
    assert restarted.state["jobs"][0]["status"] == "uncertain"


def test_uncertain_rpc_delivery_is_not_retried(setup, config):
    bridge, discord, codex = setup
    discord.since.return_value = [message(config)]
    codex.start.side_effect = dev.BridgeError("通信結果不明")
    bridge.tick()
    discord.since.return_value = []
    bridge.tick()
    codex.start.assert_called_once()
    assert bridge.state["jobs"][0]["status"] == "uncertain"


@pytest.mark.parametrize(
    "status,event",
    [
        ("completed", "completed"),
        ("failed", "failed"),
        ("interrupted", "failed"),
        ("unknown", "uncertain"),
    ],
)
def test_completion_sends_only_fixed_status_not_model_output(setup, status, event):
    bridge, discord, codex = setup
    bridge.state["cursor"] = sid(10)
    bridge.state["jobs"] = [
        {
            "id": "fake-job",
            "status": "running",
            "turn_id": "fake-turn",
            "prompt": "PRIVATE",
        }
    ]
    codex.turn_status.return_value = status
    bridge.tick()
    discord.notify.assert_called_with("fake-job", event)
    assert "PRIVATE" not in bridge.path.read_text()


def test_notifications_remain_pending_after_rate_limit(setup, config):
    bridge, discord, codex = setup
    discord.since.return_value = [message(config)]
    discord.notify.side_effect = dev.RetryLater(3)
    with pytest.raises(dev.RetryLater):
        bridge.tick()
    assert dev.private_read(bridge.path)["notices"]
    discord.since.return_value = []
    discord.notify.side_effect = None
    bridge.tick()
    codex.start.assert_called_once()


def test_state_cannot_be_reused_for_another_thread(setup, config):
    bridge, discord, codex = setup
    other = dev.Config(
        config.bot_token,
        config.owner_user_id,
        config.channel_id,
        config.guild_id,
        "00000000-0000-4000-8000-000000000001",
    )
    with pytest.raises(dev.BridgeError, match="一致"):
        dev.Bridge(other, discord, codex, bridge.path)


def test_private_configuration_permissions_and_validation(
    config, tmp_path, monkeypatch
):
    path = tmp_path / "config.json"
    monkeypatch.setattr(dev, "CONFIG", path)
    data = {k: getattr(config, k) for k in config.__dataclass_fields__}
    dev.private_write(path, data)
    assert dev.Config.load() == config
    assert "fictional-token" not in repr(config)
    path.chmod(0o644)
    with pytest.raises(dev.BridgeError, match="600"):
        dev.Config.load()
    path.chmod(0o600)
    data["bot_token"] = "bad\nvalue"
    dev.private_write(path, data)
    with pytest.raises(dev.BridgeError):
        dev.Config.load()


def test_discord_outbox_has_no_mentions_or_arbitrary_text(config):
    discord = dev.Discord(config)
    discord.request = Mock()
    discord.notify("fake-job", "completed")
    payload = discord.request.call_args.args[1]
    assert payload["content"] == dev.NOTICES["completed"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["enforce_nonce"] is True
    discord.notify("fake-job", "completed")
    assert discord.request.call_args.args[1]["nonce"] == payload["nonce"]


def test_preflight_requires_a_private_matching_guild_channel(config):
    discord = dev.Discord(config)
    channel = {
        "id": config.channel_id,
        "guild_id": config.guild_id,
        "type": 0,
        "permission_overwrites": [{"id": config.guild_id, "deny": "1024"}],
    }
    discord.request = Mock(side_effect=[{"bot": True, "id": sid(8)}, channel])
    discord.preflight()
    channel["permission_overwrites"] = []
    discord.request = Mock(side_effect=[{"bot": True, "id": sid(8)}, channel])
    with pytest.raises(dev.BridgeError, match="@everyone"):
        discord.preflight()


def test_backwards_pagination_never_skips_oldest_unread(config):
    discord = dev.Discord(config)
    newest = [{"id": sid(n)} for n in range(201, 101, -1)]
    older = [{"id": sid(n)} for n in range(101, 0, -1)]
    discord.page = Mock(side_effect=[newest, older])
    result = discord.since(sid(50))
    assert [m["id"] for m in result] == [sid(n) for n in range(51, 202)]
    assert discord.page.call_args.args[0] == sid(102)


def test_rpc_ignores_notifications_and_never_approves_server_requests(config):
    codex = dev.Codex(config)
    codex.ws = Mock()
    codex.ws.recv.side_effect = [
        json.dumps({"method": "some/notice", "params": {"PRIVATE": True}}),
        json.dumps({"id": 10, "method": "item/commandExecution/requestApproval"}),
        json.dumps({"id": 1, "result": {"ok": True}}),
    ]
    assert codex.rpc("fake", {}) == {"ok": True}
    replies = [json.loads(call.args[0]) for call in codex.ws.send.call_args_list]
    assert "error" in replies[1]
    assert "PRIVATE" not in str(replies)


def test_codex_start_preserves_existing_permissions_and_literal_prompt(config):
    codex = dev.Codex(config)
    codex.rpc = Mock(return_value={"turn": {"id": "fake-turn"}})
    assert codex.start("literal $(do-not-run-as-shell)", "fake-job") == "fake-turn"
    params = codex.rpc.call_args.args[1]
    assert set(params) == {"threadId", "clientUserMessageId", "input"}
    assert "literal $(do-not-run-as-shell)" in params["input"][0]["text"]


def test_wrong_codex_workspace_is_rejected(config):
    codex = dev.Codex(config)
    codex.rpc = Mock(
        return_value={
            "thread": {
                "cwd": str(Path("/not-this-workspace")),
                "status": {"type": "idle"},
            }
        }
    )
    with pytest.raises(dev.BridgeError, match="一致"):
        codex.status()


def test_http_failure_does_not_expose_token_or_remote_body(config, capsys):
    discord = dev.Discord(config)
    discord.opener = Mock()
    discord.opener.open.side_effect = HTTPError(
        "https://discord.com/private-marker",
        401,
        "PRIVATE-MARKER",
        {},
        BytesIO(b"PRIVATE-MARKER"),
    )
    with pytest.raises(dev.BridgeError) as error:
        discord.request("/users/@me")
    assert "PRIVATE" not in str(error.value)
    assert config.bot_token not in str(error.value)
    assert error.value.__suppress_context__
    assert capsys.readouterr() == ("", "")


def test_rate_limit_uses_server_delay_without_displaying_response(config):
    discord = dev.Discord(config)
    discord.opener = Mock()
    discord.opener.open.side_effect = HTTPError(
        "https://discord.com/",
        429,
        "PRIVATE",
        {},
        BytesIO(b'{"retry_after": 7, "private": "hidden"}'),
    )
    with pytest.raises(dev.RetryLater) as error:
        discord.request("/users/@me")
    assert error.value.delay == 7
    assert "hidden" not in str(error.value)


def prepare_retarget(config, tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "PRIVATE", tmp_path)
    monkeypatch.setattr(dev, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(dev, "STATE", tmp_path / "state.json")
    monkeypatch.setenv("CODEX_THREAD_ID", "00000000-0000-4000-8000-000000000001")
    dev.private_write(
        dev.CONFIG, {k: getattr(config, k) for k in config.__dataclass_fields__}
    )
    client = MagicMock()
    monkeypatch.setattr(dev, "Codex", client)
    return client


def test_retarget_rebinds_to_new_thread_and_archives_only_idle_state(
    config, tmp_path, monkeypatch, capsys
):
    client = prepare_retarget(config, tmp_path, monkeypatch)
    dev.private_write(dev.STATE, {"jobs": [], "cursor": sid(10)})
    dev.retarget()
    assert dev.private_read(dev.CONFIG)["thread_id"].endswith("0001")
    assert not dev.STATE.exists()
    assert len(list(tmp_path.glob("previous-state-*.json"))) == 1
    client.assert_called_once()
    assert "00000000" not in capsys.readouterr().out


def test_retarget_refuses_pending_or_uncertain_jobs(config, tmp_path, monkeypatch):
    client = prepare_retarget(config, tmp_path, monkeypatch)
    dev.private_write(dev.STATE, {"jobs": [{"status": "uncertain"}]})
    with pytest.raises(dev.BridgeError, match="未処理"):
        dev.retarget()
    assert dev.private_read(dev.CONFIG)["thread_id"] == config.thread_id
    client.assert_not_called()
