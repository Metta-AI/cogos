"""Tests for inbound attachment S3 upload in Discord bridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cogos.io.discord.bridge import DiscordBridge


def _make_bridge_with_s3():
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "test-bot"
    bridge.bot_token = "fake-token"
    bridge.reply_queue_url = ""
    bridge.region = "us-east-1"
    bridge._sqs_client = MagicMock()
    bridge._typing_tasks = {}
    bridge._repo = None
    bridge._s3_client = MagicMock()
    bridge._blob_bucket = "test-bucket"
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999
    bridge.client.user.mentioned_in = MagicMock(return_value=False)
    bridge._s3_client.generate_presigned_url.return_value = "https://s3.../presigned"
    return bridge


class TestInboundAttachments:
    async def test_upload_image_to_s3(self):
        bridge = _make_bridge_with_s3()
        attachment = MagicMock()
        attachment.url = "https://cdn.discord.com/img.png"
        attachment.filename = "img.png"
        attachment.content_type = "image/png"
        attachment.size = 1024

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"image data")

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_get_cm

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("cogos.io.discord.bridge.aiohttp.ClientSession", return_value=mock_session_cm):
            result = await bridge._upload_attachment_to_s3(attachment)

        assert result is not None
        assert "s3_key" in result
        assert result["s3_key"].startswith("blobs/")
        assert result["s3_key"].endswith("/img.png")
        assert "s3_url" in result
        assert bridge._s3_client is not None
        bridge._s3_client.put_object.assert_called_once()

    async def test_skip_large_attachment(self):
        bridge = _make_bridge_with_s3()
        attachment = MagicMock()
        attachment.url = "https://cdn.discord.com/big.zip"
        attachment.filename = "big.zip"
        attachment.content_type = "application/zip"
        attachment.size = 30_000_000
        result = await bridge._upload_attachment_to_s3(attachment)
        assert result is None
        assert bridge._s3_client is not None
        bridge._s3_client.put_object.assert_not_called()

    async def test_no_s3_client_returns_none(self):
        bridge = _make_bridge_with_s3()
        bridge._s3_client = None
        attachment = MagicMock()
        attachment.size = 100
        result = await bridge._upload_attachment_to_s3(attachment)
        assert result is None


class TestOutboundS3Files:
    async def test_download_files_with_s3_key(self):
        bridge = _make_bridge_with_s3()
        body_mock = MagicMock()
        body_mock.read.return_value = b"file data"
        assert bridge._s3_client is not None
        bridge._s3_client.get_object.return_value = {"Body": body_mock}

        import discord

        files = await bridge._download_files(
            [
                {"s3_key": "blobs/abc/chart.png", "filename": "chart.png"},
            ]
        )
        assert len(files) == 1
        assert isinstance(files[0], discord.File)
        assert bridge._s3_client is not None
        bridge._s3_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="blobs/abc/chart.png")
