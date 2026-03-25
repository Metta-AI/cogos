"""Tests for Discord SQS reply helpers."""

import json
from unittest.mock import MagicMock

import pytest

from cogos.io.discord.reply import (
    queue_dm,
    queue_reaction,
    queue_reply,
    queue_thread_create,
)


@pytest.fixture
def mock_runtime():
    """Mock runtime with send_queue_message and get_queue_url."""
    rt = MagicMock()
    rt.get_queue_url.return_value = "https://sqs.us-east-1.amazonaws.com/123456789/cogent-alpha-discord-replies"
    rt.send_queue_message = MagicMock()
    return rt


class TestQueueReply:
    async def test_sends_message_to_sqs(self, mock_runtime):
        await queue_reply(
            channel="111",
            content="hello",
            cogent_name="alpha",
            region="us-east-1",
            runtime=mock_runtime,
        )
        mock_runtime.send_queue_message.assert_called_once()
        call_args = mock_runtime.send_queue_message.call_args
        body = json.loads(call_args[0][1])
        assert body["channel"] == "111"
        assert body["content"] == "hello"
        assert "type" not in body  # default message type omitted

    async def test_includes_files_and_thread(self, mock_runtime):
        await queue_reply(
            channel="111",
            content="see attached",
            files=[{"url": "https://example.com/f.png", "filename": "f.png"}],
            thread_id="222",
            reply_to="333",
            cogent_name="alpha",
            region="us-east-1",
            runtime=mock_runtime,
        )
        body = json.loads(mock_runtime.send_queue_message.call_args[0][1])
        assert body["files"] == [{"url": "https://example.com/f.png", "filename": "f.png"}]
        assert body["thread_id"] == "222"
        assert body["reply_to"] == "333"

    async def test_queue_url_pattern(self, mock_runtime):
        mock_runtime.get_queue_url.return_value = "https://sqs.us-west-2.amazonaws.com/123456789/cogent-beta-1-discord-replies"
        await queue_reply(channel="111", content="hi", cogent_name="beta.1", region="us-west-2", runtime=mock_runtime)
        mock_runtime.get_queue_url.assert_called_with("cogent-beta-1-discord-replies")


class TestQueueReaction:
    async def test_sends_reaction(self, mock_runtime):
        await queue_reaction(
            channel="111",
            message_id="999",
            emoji="\U0001f44d",
            cogent_name="alpha",
            region="us-east-1",
            runtime=mock_runtime,
        )
        body = json.loads(mock_runtime.send_queue_message.call_args[0][1])
        assert body["type"] == "reaction"
        assert body["emoji"] == "\U0001f44d"
        assert body["message_id"] == "999"


class TestQueueThreadCreate:
    async def test_sends_thread_create(self, mock_runtime):
        await queue_thread_create(
            channel="111",
            thread_name="Discussion",
            content="Let's talk",
            cogent_name="alpha",
            region="us-east-1",
            runtime=mock_runtime,
        )
        body = json.loads(mock_runtime.send_queue_message.call_args[0][1])
        assert body["type"] == "thread_create"
        assert body["thread_name"] == "Discussion"
        assert body["content"] == "Let's talk"


class TestQueueDm:
    async def test_sends_dm(self, mock_runtime):
        await queue_dm(
            user_id="777",
            content="hey there",
            cogent_name="alpha",
            region="us-east-1",
            runtime=mock_runtime,
        )
        body = json.loads(mock_runtime.send_queue_message.call_args[0][1])
        assert body["type"] == "dm"
        assert body["user_id"] == "777"
        assert body["content"] == "hey there"
