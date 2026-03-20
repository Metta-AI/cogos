from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import (
    Channel,
    ChannelType,
    Delivery,
    DeliveryStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
)
from dashboard.app import create_app


class _Payload:
    def __init__(self, body: str) -> None:
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body


class _LambdaClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def invoke(self, *, FunctionName: str, InvocationType: str, Payload: str):
        self.payloads.append(json.loads(Payload))
        return {
            "Payload": _Payload(
                json.dumps(
                    {
                        "web_response": {
                            "status": 200,
                            "headers": {"content-type": "application/json"},
                            "body": json.dumps({"ok": True}),
                        }
                    }
                )
            )
        }


class _WebProxyRepoStub:
    def __init__(self) -> None:
        self.channel = Channel(id=uuid4(), name="io:web:request", channel_type=ChannelType.NAMED)
        self.process = Process(
            id=uuid4(),
            name="web.handler",
            mode=ProcessMode.DAEMON,
            status=ProcessStatus.WAITING,
            runner="lambda",
        )
        self.handler = Handler(id=uuid4(), process=self.process.id, channel=self.channel.id, enabled=True)
        self.message_id = uuid4()
        self.delivery = Delivery(
            id=uuid4(),
            message=self.message_id,
            handler=self.handler.id,
            status=DeliveryStatus.PENDING,
        )
        self.created_runs = []
        self.queued = []
        self.status_updates = []
        self.rolled_back = None

    def get_channel_by_name(self, name: str):
        return self.channel if name == self.channel.name else None

    def match_handlers_by_channel(self, channel_id):
        return [self.handler] if channel_id == self.channel.id else []

    def get_process(self, process_id):
        return self.process if process_id == self.process.id else None

    def append_channel_message(self, message):
        self.last_message = message
        return self.message_id

    def list_deliveries(self, *, message_id=None, handler_id=None, run_id=None, limit: int = 500):
        if message_id == self.message_id and handler_id == self.handler.id:
            return [self.delivery]
        return []

    def update_process_status(self, process_id, status):
        self.status_updates.append((process_id, status))

    def create_run(self, run):
        self.created_runs.append(run)
        return run.id

    def mark_queued(self, delivery_id, run_id):
        self.queued.append((delivery_id, run_id))
        return True

    def rollback_dispatch(self, process_id, run_id, delivery_id=None, *, error=None):
        self.rolled_back = (process_id, run_id, delivery_id, error)


def test_web_proxy_queues_linked_run_and_passes_message_id(monkeypatch):
    app = create_app()
    client = TestClient(app)
    repo = _WebProxyRepoStub()
    lambda_client = _LambdaClient()

    monkeypatch.setenv("EXECUTOR_FUNCTION_NAME", "test-executor")

    with patch("dashboard.db.get_repo", return_value=repo), patch("boto3.client", return_value=lambda_client):
        response = client.get("/web/api/status")

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    assert len(repo.created_runs) == 1
    created_run = repo.created_runs[0]
    assert created_run.message == repo.message_id

    assert repo.queued == [(repo.delivery.id, created_run.id)]
    assert repo.rolled_back is None

    assert len(lambda_client.payloads) == 1
    payload = lambda_client.payloads[0]
    assert payload["process_id"] == str(repo.process.id)
    assert payload["message_id"] == str(repo.message_id)
    assert payload["run_id"] == str(created_run.id)
    assert payload["web_request"]["path"] == "status"
