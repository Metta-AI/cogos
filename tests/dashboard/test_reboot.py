from unittest.mock import patch

from fastapi.testclient import TestClient

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_reboot_endpoint(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="test", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    with patch("dashboard.routers.processes.get_repo", return_value=repo):
        from dashboard.app import create_app
        app = create_app()
        client = TestClient(app)
        resp = client.post("/api/cogents/test-cogent/reboot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cleared_processes"] >= 1
        assert "epoch" in data

    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"
