"""E2E tests for Discord reaction identity: cog emoji on sent messages.

Tests the full flow:
1. CogConfig.emoji field
2. discord.send(react=...) includes react in SQS payload
3. discord.dm(react=...) includes react in SQS payload
4. Bridge._maybe_react adds reaction to sent message
5. Worker make_coglet inherits emoji from parent cog config
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from cogos.cog.cog import Cog, CogConfig
from cogos.io.discord.capability import DiscordCapability
from cogos.io.discord.bridge import DiscordBridge


# ── CogConfig emoji ──────────────────────────────────────


class TestCogConfigEmoji:
    def test_default_emoji_is_empty(self):
        config = CogConfig()
        assert config.emoji == ""

    def test_emoji_round_trips(self):
        config = CogConfig(emoji="🧠")
        assert config.emoji == "🧠"
        dumped = config.model_dump()
        assert dumped["emoji"] == "🧠"
        restored = CogConfig(**dumped)
        assert restored.emoji == "🧠"

    def test_emoji_from_cog_dir(self, tmp_path):
        cog_dir = tmp_path / "mycog"
        cog_dir.mkdir()
        (cog_dir / "cog.py").write_text(
            "from cogos.cog.cog import CogConfig\n"
            "config = CogConfig(emoji='🔧')\n"
        )
        (cog_dir / "main.md").write_text("# My Cog")
        cog = Cog(cog_dir)
        assert cog.config.emoji == "🔧"


# ── discord.send() react param ───────────────────────────


class TestDiscordSendReact:
    @patch("cogos.io.discord.capability._send_sqs")
    def test_send_includes_react_in_payload(self, mock_sqs):
        cap = DiscordCapability(MagicMock(), uuid4())
        cap.send("chan-1", "hello", react="🔧")

        body = mock_sqs.call_args.args[0]
        assert body["react"] == "🔧"

    @patch("cogos.io.discord.capability._send_sqs")
    def test_send_omits_react_when_none(self, mock_sqs):
        cap = DiscordCapability(MagicMock(), uuid4())
        cap.send("chan-1", "hello")

        body = mock_sqs.call_args.args[0]
        assert "react" not in body

    @patch("cogos.io.discord.capability._send_sqs")
    def test_send_omits_react_when_empty(self, mock_sqs):
        cap = DiscordCapability(MagicMock(), uuid4())
        cap.send("chan-1", "hello", react="")

        body = mock_sqs.call_args.args[0]
        assert "react" not in body

    @patch("cogos.io.discord.capability._send_sqs")
    def test_dm_includes_react_in_payload(self, mock_sqs):
        cap = DiscordCapability(MagicMock(), uuid4())
        cap.dm("user-1", "hey", react="🧠")

        body = mock_sqs.call_args.args[0]
        assert body["react"] == "🧠"

    @patch("cogos.io.discord.capability._send_sqs")
    def test_dm_omits_react_when_none(self, mock_sqs):
        cap = DiscordCapability(MagicMock(), uuid4())
        cap.dm("user-1", "hey")

        body = mock_sqs.call_args.args[0]
        assert "react" not in body


# ── Bridge _maybe_react ──────────────────────────────────


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge._typing_tasks = {}
    bridge._s3_client = None
    bridge._blob_bucket = ""
    return bridge


class TestBridgeMaybeReact:
    async def test_adds_reaction_when_react_present(self):
        bridge = _make_bridge()
        message = AsyncMock()
        message.id = 123

        await bridge._maybe_react(message, {"react": "🔧"})
        message.add_reaction.assert_called_once_with("🔧")

    async def test_skips_when_no_react(self):
        bridge = _make_bridge()
        message = AsyncMock()

        await bridge._maybe_react(message, {"content": "hello"})
        message.add_reaction.assert_not_called()

    async def test_skips_when_message_is_none(self):
        bridge = _make_bridge()
        # Should not raise
        await bridge._maybe_react(None, {"react": "🔧"})

    async def test_logs_warning_on_reaction_failure(self):
        bridge = _make_bridge()
        message = AsyncMock()
        message.id = 456
        message.add_reaction.side_effect = Exception("Discord API error")

        # Should not raise
        await bridge._maybe_react(message, {"react": "🔧"})
        message.add_reaction.assert_called_once_with("🔧")


class TestBridgeHandleMessageReact:
    async def test_handle_message_reacts_after_send(self):
        bridge = _make_bridge()
        bridge._log_reply_send_latency = MagicMock()
        bridge._log_trace_summary = MagicMock()

        channel = AsyncMock()
        sent_message = AsyncMock()
        sent_message.id = 789
        channel.send.return_value = sent_message

        body = {"content": "hello", "react": "🔧"}
        await bridge._handle_message(body, channel)

        channel.send.assert_called_once()
        sent_message.add_reaction.assert_called_once_with("🔧")

    async def test_handle_message_no_react(self):
        bridge = _make_bridge()
        bridge._log_reply_send_latency = MagicMock()
        bridge._log_trace_summary = MagicMock()

        channel = AsyncMock()
        sent_message = AsyncMock()
        channel.send.return_value = sent_message

        body = {"content": "hello"}
        await bridge._handle_message(body, channel)

        sent_message.add_reaction.assert_not_called()


class TestBridgeHandleDmReact:
    async def test_handle_dm_reacts_after_send(self):
        bridge = _make_bridge()
        bridge._stop_typing = MagicMock()
        bridge._log_reply_send_latency = MagicMock()
        bridge._log_trace_summary = MagicMock()

        mock_user = AsyncMock()
        mock_dm_channel = AsyncMock()
        mock_dm_channel.id = 444
        sent_message = AsyncMock()
        sent_message.id = 555
        mock_dm_channel.send.return_value = sent_message
        mock_user.create_dm.return_value = mock_dm_channel
        bridge.client.fetch_user = AsyncMock(return_value=mock_user)

        body = {
            "user_id": "777",
            "content": "hey there",
            "react": "🧠",
        }
        await bridge._handle_dm(body)

        mock_dm_channel.send.assert_called_once()
        sent_message.add_reaction.assert_called_once_with("🧠")

    async def test_handle_dm_no_react(self):
        bridge = _make_bridge()
        bridge._stop_typing = MagicMock()
        bridge._log_reply_send_latency = MagicMock()
        bridge._log_trace_summary = MagicMock()

        mock_user = AsyncMock()
        mock_dm_channel = AsyncMock()
        mock_dm_channel.id = 444
        sent_message = AsyncMock()
        mock_dm_channel.send.return_value = sent_message
        mock_user.create_dm.return_value = mock_dm_channel
        bridge.client.fetch_user = AsyncMock(return_value=mock_user)

        body = {
            "user_id": "777",
            "content": "hey there",
        }
        await bridge._handle_dm(body)

        sent_message.add_reaction.assert_not_called()


# ── Worker make_coglet inherits emoji ─────────────────────


class TestWorkerMakeCogletEmoji:
    def test_make_coglet_inherits_emoji(self, tmp_path):
        """Worker cog's make_coglet inherits emoji from parent cog config."""
        worker_dir = tmp_path / "worker"
        worker_dir.mkdir()

        (worker_dir / "cog.py").write_text(
            "from cogos.cog.cog import CogConfig\n"
            "config = CogConfig(mode='one_shot', emoji='🔧', capabilities=['channels'])\n"
        )
        (worker_dir / "main.md").write_text("# Worker\nDo the task.\n")
        (worker_dir / "make_coglet.py").write_text(
            (Path(__file__).resolve().parents[3] / "images" / "cogent-v1" / "cogos" / "worker" / "make_coglet.py").read_text()
        )

        cog = Cog(worker_dir)
        coglet, caps = cog.make_coglet("Test task")

        assert coglet.config.emoji == "🔧"

    def test_make_coglet_empty_emoji_when_parent_has_none(self, tmp_path):
        """Worker cog without emoji produces coglet with empty emoji."""
        worker_dir = tmp_path / "worker"
        worker_dir.mkdir()

        (worker_dir / "cog.py").write_text(
            "from cogos.cog.cog import CogConfig\n"
            "config = CogConfig(mode='one_shot', capabilities=['channels'])\n"
        )
        (worker_dir / "main.md").write_text("# Worker\nDo the task.\n")
        (worker_dir / "make_coglet.py").write_text(
            (Path(__file__).resolve().parents[3] / "images" / "cogent-v1" / "cogos" / "worker" / "make_coglet.py").read_text()
        )

        cog = Cog(worker_dir)
        coglet, caps = cog.make_coglet("Test task")

        assert coglet.config.emoji == ""
