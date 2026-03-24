from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from cogos.db.repository import RdsDataApiRepository


def test_list_channel_messages_allows_null_sender_process():
    repo = RdsDataApiRepository.__new__(RdsDataApiRepository)
    channel_id = uuid4()
    msg_id = uuid4()
    created_at = datetime.now(timezone.utc)

    repo._execute = MagicMock(return_value=object())
    repo._rows_to_dicts = MagicMock(return_value=[{
        "id": str(msg_id),
        "channel": str(channel_id),
        "sender_process": None,
        "payload": {"content": "hello"},
        "created_at": "2026-03-13T00:00:00+00:00",
    }])
    repo._json_field = lambda row, key, default=None: row.get(key, default)
    repo._ts = lambda row, key: created_at

    messages = RdsDataApiRepository.list_channel_messages(repo, channel_id)

    assert len(messages) == 1
    assert messages[0].id == msg_id
    assert messages[0].channel == channel_id
    assert messages[0].sender_process is None
    assert messages[0].payload == {"content": "hello"}
    assert messages[0].created_at == created_at
