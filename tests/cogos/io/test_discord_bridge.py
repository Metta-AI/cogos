from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cogos.io.discord.bridge import DiscordBridge, _reply_queue_latency_ms


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge._typing_tasks = {}
    return bridge


async def test_handle_dm_stops_typing_on_dm_channel():
    bridge = _make_bridge()
    bridge._stop_typing = MagicMock()
    bridge._log_reply_send_latency = MagicMock()

    mock_user = AsyncMock()
    mock_dm_channel = AsyncMock()
    mock_dm_channel.id = 444
    mock_user.create_dm.return_value = mock_dm_channel
    bridge.client.fetch_user = AsyncMock(return_value=mock_user)

    body = {
        "user_id": "777",
        "content": "hi there",
        "_meta": {"queued_at_ms": 1000, "trace_id": "trace-1"},
    }
    await bridge._handle_dm(body)

    bridge.client.fetch_user.assert_called_once_with(777)
    mock_user.create_dm.assert_called_once()
    bridge._stop_typing.assert_called_once_with(444)
    mock_dm_channel.send.assert_called_once_with("hi there")
    bridge._log_reply_send_latency.assert_called_once_with(body, msg_type="dm", target_id=444)


def test_reply_queue_latency_ms_uses_enqueued_timestamp():
    with patch("cogos.io.discord.bridge.time.time", return_value=10.0):
        assert _reply_queue_latency_ms({"_meta": {"queued_at_ms": "9500"}}) == 500
