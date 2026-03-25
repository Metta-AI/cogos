from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.db.sqlite_repository import SqliteRepository
from dashboard.app import create_app


def test_get_process_logs_returns_stdout_stderr(tmp_path):
    """GET /processes/{id}/logs returns stdout and stderr entries."""
    repo = SqliteRepository(str(tmp_path))

    process = Process(
        id=uuid4(),
        name="test-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNABLE,
        required_tags=["local"],
    )
    repo.upsert_process(process)

    stdout_ch = Channel(name="process:test-proc:stdout", channel_type=ChannelType.IMPLICIT)
    repo.upsert_channel(stdout_ch)
    stderr_ch = Channel(name="process:test-proc:stderr", channel_type=ChannelType.IMPLICIT)
    repo.upsert_channel(stderr_ch)

    stdout_msg = ChannelMessage(
        channel=stdout_ch.id,
        payload={"text": "hello stdout", "process": "test-proc"},
    )
    repo.append_channel_message(stdout_msg)

    stderr_msg = ChannelMessage(
        channel=stderr_ch.id,
        payload={"text": "hello stderr", "process": "test-proc"},
    )
    repo.append_channel_message(stderr_msg)

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.processes.get_repo", return_value=repo):
        resp = client.get(f"/api/cogents/test/processes/{process.id}/logs")

    assert resp.status_code == 200
    data = resp.json()
    assert data["process_name"] == "test-proc"
    assert len(data["entries"]) == 2
    streams = {e["stream"] for e in data["entries"]}
    assert "stdout" in streams
    assert "stderr" in streams


def test_get_process_logs_404_for_missing_process(tmp_path):
    """GET /processes/{id}/logs returns 404 when process does not exist."""
    repo = SqliteRepository(str(tmp_path))

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.processes.get_repo", return_value=repo):
        resp = client.get(f"/api/cogents/test/processes/{uuid4()}/logs")

    assert resp.status_code == 404


def test_get_process_logs_empty_when_no_channels(tmp_path):
    """GET /processes/{id}/logs returns empty entries when no IO channels exist."""
    repo = SqliteRepository(str(tmp_path))

    process = Process(
        id=uuid4(),
        name="quiet-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNABLE,
        required_tags=["local"],
    )
    repo.upsert_process(process)

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.processes.get_repo", return_value=repo):
        resp = client.get(f"/api/cogents/test/processes/{process.id}/logs")

    assert resp.status_code == 200
    data = resp.json()
    assert data["process_name"] == "quiet-proc"
    assert data["entries"] == []
