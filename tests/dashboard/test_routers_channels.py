from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus, Schema
from dashboard.app import create_app


class _ChannelsRepoStub:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.process = Process(
            id=uuid4(),
            name="test-daemon",
            mode=ProcessMode.DAEMON,
            status=ProcessStatus.WAITING,
            required_tags=[],
            created_at=now,
        )
        self.channel = Channel(
            id=uuid4(),
            name="test:requests",
            owner_process=self.process.id,
            channel_type=ChannelType.NAMED,
            inline_schema={"fields": {"prefix": "string", "reason": "string"}},
            created_at=now,
        )
        self.schema = Schema(
            id=uuid4(),
            name="audit-request",
            definition={"fields": {"prefix": "string"}},
        )
        self.schema_channel = Channel(
            id=uuid4(),
            name="test:findings",
            channel_type=ChannelType.NAMED,
            schema_id=self.schema.id,
            created_at=now,
        )
        self.spawn_channel = Channel(
            id=uuid4(),
            name="spawn:parent→child",
            channel_type=ChannelType.SPAWN,
            created_at=now,
        )
        self.appended_messages: list[dict] = []
        self.channel_message = ChannelMessage(
            id=uuid4(),
            channel=self.channel.id,
            sender_process=None,
            payload={"prefix": "workspace/", "reason": "manual replay"},
            created_at=now,
        )

    def get_channel(self, channel_id):
        if channel_id == self.channel.id:
            return self.channel
        if channel_id == self.schema_channel.id:
            return self.schema_channel
        if channel_id == self.spawn_channel.id:
            return self.spawn_channel
        return None

    def get_schema(self, schema_id):
        return self.schema if schema_id == self.schema.id else None

    def list_schemas(self):
        return [self.schema]

    def append_channel_message(self, message):
        self.appended_messages.append(message.model_dump())
        return uuid4()

    def list_channels(self, owner_process=None, limit=0):
        channels = [self.channel, self.schema_channel, self.spawn_channel]
        if owner_process is None:
            return channels
        return [channel for channel in channels if channel.owner_process == owner_process]

    def list_processes(self, *, limit=1000):
        return [self.process]

    def list_channel_messages(self, channel_id, *, limit=100):
        if channel_id == self.channel.id:
            return [self.channel_message]
        return []

    def match_handlers_by_channel(self, channel_id):
        return [object()] if channel_id == self.channel.id else []


def test_send_channel_message_accepts_valid_named_channel_payload():
    app = create_app()
    client = TestClient(app)
    repo = _ChannelsRepoStub()

    with patch("dashboard.routers.channels.get_repo", return_value=repo):
        response = client.post(
            f"/api/cogents/test/channels/{repo.channel.id}/messages",
            json={"payload": {"prefix": "workspace/", "reason": "manual replay"}},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["channel_name"] == "test:requests"
    assert payload["payload"]["prefix"] == "workspace/"
    assert len(repo.appended_messages) == 1
    assert repo.appended_messages[0]["sender_process"] is None


def test_list_channels_includes_resolved_schema_metadata():
    app = create_app()
    client = TestClient(app)
    repo = _ChannelsRepoStub()

    with patch("dashboard.routers.channels.get_repo", return_value=repo):
        response = client.get("/api/cogents/test/channels?channel_type=named")

    assert response.status_code == 200
    channels = response.json()["channels"]
    request_channel = next(channel for channel in channels if channel["name"] == "test:requests")
    findings_channel = next(channel for channel in channels if channel["name"] == "test:findings")

    # List view omits schema_definition and inline_schema to reduce payload size
    assert request_channel["schema_definition"] is None
    assert request_channel["schema_name"] is None
    assert findings_channel["schema_name"] == "audit-request"
    assert findings_channel["schema_definition"] is None


def test_send_channel_message_validates_payload_against_channel_schema():
    app = create_app()
    client = TestClient(app)
    repo = _ChannelsRepoStub()

    with patch("dashboard.routers.channels.get_repo", return_value=repo):
        response = client.post(
            f"/api/cogents/test/channels/{repo.schema_channel.id}/messages",
            json={"payload": {"wrong": "shape"}},
        )

    assert response.status_code == 400
    assert "Schema validation failed" in response.json()["detail"]
    assert repo.appended_messages == []


def test_send_channel_message_rejects_non_named_channels():
    app = create_app()
    client = TestClient(app)
    repo = _ChannelsRepoStub()

    with patch("dashboard.routers.channels.get_repo", return_value=repo):
        response = client.post(
            f"/api/cogents/test/channels/{repo.spawn_channel.id}/messages",
            json={"payload": {"task": "go"}},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only named channels can receive dashboard-composed messages"
