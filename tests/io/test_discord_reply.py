"""Tests for Discord SQS reply helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from cogos.io.discord.reply import (
    queue_reply,
    queue_reaction,
    queue_thread_create,
    queue_dm,
)


@pytest.fixture
def mock_sqs():
    """Mock SQS client and patch boto3 + STS."""
    sqs = MagicMock()
    with (
        patch("cogos.io.discord.reply.boto3") as mock_boto3,
    ):
        mock_boto3.client.side_effect = lambda service, **kw: (
            sqs if service == "sqs" else MagicMock(get_caller_identity=MagicMock(return_value={"Account": "123456789"}))
        )
        yield sqs


class TestQueueReply:
    async def test_sends_message_to_sqs(self, mock_sqs):
        await queue_reply(
            channel="111",
            content="hello",
            cogent_name="alpha",
            region="us-east-1",
        )
        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        body = json.loads(call_kwargs["MessageBody"])
        assert body["channel"] == "111"
        assert body["content"] == "hello"
        assert "type" not in body  # default message type omitted

    async def test_includes_files_and_thread(self, mock_sqs):
        await queue_reply(
            channel="111",
            content="see attached",
            files=[{"url": "https://example.com/f.png", "filename": "f.png"}],
            thread_id="222",
            reply_to="333",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["files"] == [{"url": "https://example.com/f.png", "filename": "f.png"}]
        assert body["thread_id"] == "222"
        assert body["reply_to"] == "333"

    async def test_queue_url_pattern(self, mock_sqs):
        await queue_reply(channel="111", content="hi", cogent_name="beta.1", region="us-west-2")
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert "cogent-beta-1-discord-replies" in call_kwargs["QueueUrl"]
        assert "us-west-2" in call_kwargs["QueueUrl"]


class TestQueueReaction:
    async def test_sends_reaction(self, mock_sqs):
        await queue_reaction(
            channel="111",
            message_id="999",
            emoji="\U0001f44d",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["type"] == "reaction"
        assert body["emoji"] == "\U0001f44d"
        assert body["message_id"] == "999"


class TestQueueThreadCreate:
    async def test_sends_thread_create(self, mock_sqs):
        await queue_thread_create(
            channel="111",
            thread_name="Discussion",
            content="Let's talk",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["type"] == "thread_create"
        assert body["thread_name"] == "Discussion"
        assert body["content"] == "Let's talk"


class TestQueueDm:
    async def test_sends_dm(self, mock_sqs):
        await queue_dm(
            user_id="777",
            content="hey there",
            cogent_name="alpha",
            region="us-east-1",
        )
        body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert body["type"] == "dm"
        assert body["user_id"] == "777"
        assert body["content"] == "hey there"
