from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Delivery,
    DeliveryStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from dashboard.app import create_app


class _RequestFlowRepoStub:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.api_process = Process(
            id=uuid4(),
            name="api.router",
            mode=ProcessMode.DAEMON,
            status=ProcessStatus.WAITING,
            runner="lambda",
        )
        self.worker_process = Process(
            id=uuid4(),
            name="tasks.worker",
            mode=ProcessMode.DAEMON,
            status=ProcessStatus.WAITING,
            runner="python",
        )

        self.request_channel = Channel(
            id=uuid4(),
            name="io:web:request",
            channel_type=ChannelType.NAMED,
        )
        self.worker_channel = Channel(
            id=uuid4(),
            name="tasks:fetch",
            channel_type=ChannelType.NAMED,
        )

        self.root_message = ChannelMessage(
            id=uuid4(),
            channel=self.request_channel.id,
            payload={
                "request_id": "req-123",
                "method": "GET",
                "path": "/api/tasks",
                "message_type": "web:request",
            },
            created_at=now,
        )
        self.handler_one = Handler(
            id=uuid4(),
            process=self.api_process.id,
            channel=self.request_channel.id,
            enabled=True,
            created_at=now + timedelta(milliseconds=10),
        )
        self.run_one = Run(
            id=uuid4(),
            process=self.api_process.id,
            message=self.root_message.id,
            status=RunStatus.COMPLETED,
            tokens_in=30,
            tokens_out=15,
            cost_usd=Decimal("0.01"),
            duration_ms=900,
            created_at=now + timedelta(milliseconds=100),
            completed_at=now + timedelta(seconds=1),
        )
        self.delivery_one = Delivery(
            id=uuid4(),
            message=self.root_message.id,
            handler=self.handler_one.id,
            status=DeliveryStatus.DELIVERED,
            run=self.run_one.id,
            created_at=now + timedelta(milliseconds=30),
        )

        self.worker_message = ChannelMessage(
            id=uuid4(),
            channel=self.worker_channel.id,
            sender_process=self.api_process.id,
            payload={
                "request_id": "req-123",
                "message_type": "tasks:fetch",
                "task_id": "task-42",
            },
            created_at=now + timedelta(milliseconds=500),
        )
        self.handler_two = Handler(
            id=uuid4(),
            process=self.worker_process.id,
            channel=self.worker_channel.id,
            enabled=True,
            created_at=now + timedelta(milliseconds=550),
        )
        self.run_two = Run(
            id=uuid4(),
            process=self.worker_process.id,
            message=self.worker_message.id,
            status=RunStatus.COMPLETED,
            tokens_in=12,
            tokens_out=8,
            cost_usd=Decimal("0.003"),
            duration_ms=600,
            created_at=now + timedelta(milliseconds=650),
            completed_at=now + timedelta(seconds=2),
        )
        self.delivery_two = Delivery(
            id=uuid4(),
            message=self.worker_message.id,
            handler=self.handler_two.id,
            status=DeliveryStatus.DELIVERED,
            run=self.run_two.id,
            created_at=now + timedelta(milliseconds=600),
        )

    def list_processes(self, *, limit: int = 1000):
        return [self.api_process, self.worker_process]

    def list_channels(self):
        return [self.request_channel, self.worker_channel]

    def list_handlers(self):
        return [self.handler_one, self.handler_two]

    def list_channel_messages(self, channel_id=None, *, limit: int = 100):
        messages = [self.worker_message, self.root_message]
        if channel_id is not None:
            messages = [message for message in messages if message.channel == channel_id]
        return messages[:limit]

    def list_deliveries(self, *, message_id=None, handler_id=None, run_id=None, limit: int = 500):
        deliveries = [self.delivery_one, self.delivery_two]
        if message_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.message == message_id]
        if handler_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.handler == handler_id]
        if run_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.run == run_id]
        return deliveries[:limit]

    def list_runs(self, *, process_id=None, limit: int = 50):
        runs = [self.run_two, self.run_one]
        if process_id is not None:
            runs = [run for run in runs if run.process == process_id]
        return runs[:limit]


def test_request_flows_endpoint_returns_recursive_request_graph():
    app = create_app()
    client = TestClient(app)
    repo = _RequestFlowRepoStub()

    with patch("dashboard.routers.request_flows.get_repo", return_value=repo):
        response = client.get("/api/cogents/test/request-flows?range=1h")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1

    flow = payload["flows"][0]
    assert flow["request_id"] == "req-123"
    assert flow["status"] == "completed"
    assert flow["method"] == "GET"
    assert flow["path"] == "/api/tasks"
    assert flow["total_runs"] == 2
    assert flow["total_edges"] == 2
    assert flow["total_messages"] == 2
    assert flow["root_message"]["id"] == str(repo.root_message.id)

    node_kinds = {node["kind"] for node in flow["nodes"]}
    assert node_kinds == {"request", "process"}
    process_names = {node["process_name"] for node in flow["nodes"] if node["kind"] == "process"}
    assert process_names == {"api.router", "tasks.worker"}

    edge_channels = [edge["channel_name"] for edge in flow["edges"]]
    assert edge_channels == ["io:web:request", "tasks:fetch"]

    timeline_kinds = {entry["kind"] for entry in flow["timeline"]}
    assert "request_received" in timeline_kinds
    assert "handler_matched" in timeline_kinds
    assert "run_started" in timeline_kinds
    assert "run_completed" in timeline_kinds
    assert "message_emitted" in timeline_kinds
