from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, Run, RunStatus
from dashboard.app import create_app


def test_runs_endpoint_supports_message_backed_runs(tmp_path, monkeypatch):
    repo = LocalRepository(str(tmp_path))
    process = Process(name="worker")
    repo.upsert_process(process)

    run = Run(process=process.id, message=uuid4(), status=RunStatus.COMPLETED, tokens_in=5, tokens_out=7)
    repo.create_run(run)

    monkeypatch.setattr("dashboard.routers.runs.get_repo", lambda: repo)
    client = TestClient(create_app())

    resp = client.get("/api/cogents/test/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["runs"][0]["id"] == str(run.id)
    assert data["runs"][0]["message"] == str(run.message)
    assert data["runs"][0]["process_name"] == "worker"
