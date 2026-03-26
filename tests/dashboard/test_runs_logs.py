from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore
from dashboard.app import create_app


def test_run_logs_endpoint_prefers_session_artifacts(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="alpha.worker",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=["local"],
    )
    repo.upsert_process(process)

    run = Run(id=uuid4(), process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    session_base = f"/proc/{process.id}/_sessions/process-test"
    run_base = f"{session_base}/runs/{run.id}"
    steps_key = f"{run_base}/steps"
    trigger_key = f"{run_base}/trigger.json"
    final_key = f"{run_base}/final.json"
    checkpoint_key = f"{session_base}/checkpoint.json"
    manifest_key = f"{session_base}/manifest.json"
    store = FileStore(repo)
    store.upsert(
        trigger_key,
        json.dumps(
            {
                "created_at": "2026-03-13T20:52:08.000000+00:00",
                "event": {"payload": {"text": "hello"}},
                "user_message": {"role": "user", "content": [{"text": "hello"}]},
            }
        ),
        source="test",
    )
    store.upsert(
        f"{steps_key}/0001.json",
        json.dumps(
            {
                "created_at": "2026-03-13T20:52:09.000000+00:00",
                "type": "trigger_loaded",
                "message": {"role": "user", "content": [{"text": "hello"}]},
            }
        ),
        source="test",
    )
    store.upsert(
        f"{steps_key}/0002.json",
        json.dumps(
            {
                "created_at": "2026-03-13T20:52:10.000000+00:00",
                "type": "assistant_message",
                "turn_number": 1,
                "message": {"role": "assistant", "content": [{"text": "done"}]},
            }
        ),
        source="test",
    )
    store.upsert(
        checkpoint_key,
        json.dumps(
            {
                "updated_at": "2026-03-13T20:52:11.000000+00:00",
                "last_completed_step": 2,
                "message_count": 2,
                "resumable": True,
                "source_run_id": str(run.id),
            }
        ),
        source="test",
    )
    store.upsert(
        manifest_key,
        json.dumps(
            {
                "updated_at": "2026-03-13T20:52:12.000000+00:00",
                "latest_run_id": str(run.id),
                "latest_final_key": final_key,
            }
        ),
        source="test",
    )
    store.upsert(
        final_key,
        json.dumps(
            {
                "finalized_at": "2026-03-13T20:52:13.000000+00:00",
                "status": "completed",
                "trigger_key": trigger_key,
                "steps_key": steps_key,
                "checkpoint_key": checkpoint_key,
                "manifest_key": manifest_key,
            }
        ),
        source="test",
    )

    repo.complete_run(
        run.id,
        status=RunStatus.COMPLETED,
        snapshot={
            "final_key": final_key,
            "checkpoint_key": checkpoint_key,
            "manifest_key": manifest_key,
        },
    )
    store.upsert(
        checkpoint_key,
        json.dumps(
            {
                "updated_at": "2026-03-13T21:00:00.000000+00:00",
                "last_completed_step": 99,
                "message_count": 99,
                "resumable": False,
                "source_run_id": "later-run",
            }
        ),
        source="test",
    )
    store.upsert(
        manifest_key,
        json.dumps(
            {
                "updated_at": "2026-03-13T21:00:01.000000+00:00",
                "latest_run_id": "later-run",
                "latest_final_key": "/proc/later/final.json",
            }
        ),
        source="test",
    )

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get(f"/api/cogents/test/runs/{run.id}/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["log_group"] == "CogOS session artifacts"
    assert payload["log_stream"] == run_base
    assert len(payload["entries"]) == 6
    assert "trigger" in payload["entries"][0]["message"]
    assert "trigger_loaded" in payload["entries"][1]["message"]
    assert "assistant_message" in payload["entries"][2]["message"]
    assert "final | status=completed" in payload["entries"][3]["message"]
    assert "checkpoint | last_step=2 | resumable" in payload["entries"][4]["message"]
    assert "later-run" not in payload["entries"][4]["message"]
    assert f"manifest | latest_run={run.id}" in payload["entries"][5]["message"]
    assert "later-run" not in payload["entries"][5]["message"]


def test_run_logs_endpoint_without_session_artifacts_returns_empty(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="alpha.worker",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=["local"],
    )
    repo.upsert_process(process)

    run = Run(id=uuid4(), process=process.id, status=RunStatus.COMPLETED)
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.COMPLETED)

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get(f"/api/cogents/test/runs/{run.id}/logs")

    assert response.status_code == 200
    assert response.json() == {
        "log_group": "Python executor output",
        "log_stream": None,
        "entries": [],
        "error": None,
    }


def test_run_logs_endpoint_surfaces_python_executor_output(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="init",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
    )
    repo.upsert_process(process)

    run = Run(id=uuid4(), process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    repo.complete_run(
        run.id,
        status=RunStatus.COMPLETED,
        result={"output": "Started cog: discord\nStarted cog: github\nInit complete"},
    )

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get(f"/api/cogents/test/runs/{run.id}/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["log_group"] == "Python executor output"
    assert len(payload["entries"]) == 3
    assert payload["entries"][0]["message"] == "Started cog: discord"
    assert payload["entries"][2]["message"] == "Init complete"
    assert all(e["log_stream"] == "stdout" for e in payload["entries"])
