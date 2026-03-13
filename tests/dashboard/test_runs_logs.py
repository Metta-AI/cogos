from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType, Handler, Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor import handler as executor_handler
from cogos.files.store import FileStore
from cogos.runtime.ingress import dispatch_ready_processes
from cogos.runtime.local import run_and_complete
from dashboard.app import create_app


def test_run_logs_endpoint_prefers_session_artifacts(tmp_path):
    repo = LocalRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="alpha.worker",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="local",
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
    repo = LocalRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="alpha.worker",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="local",
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
        "log_group": "CogOS session artifacts",
        "log_stream": None,
        "entries": [],
        "error": None,
    }


def test_run_logs_endpoint_returns_dispatch_failure_artifacts(tmp_path):
    repo = LocalRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="alpha.worker",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(process)

    channel = Channel(name="io:test", channel_type=ChannelType.NAMED)
    repo.upsert_channel(channel)
    channel = repo.get_channel_by_name("io:test")
    repo.create_handler(Handler(process=process.id, channel=channel.id))
    repo.append_channel_message(ChannelMessage(channel=channel.id, payload={"content": "hello"}))

    scheduler = SchedulerCapability(repo, uuid4())

    class _LambdaClient:
        def invoke(self, **_kwargs):
            raise RuntimeError("invoke throttled")

    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        _LambdaClient(),
        "executor-fn",
        {process.id},
    )

    assert dispatched == 0
    run = repo.list_runs(process_id=process.id)[0]
    assert run.snapshot is not None

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get(f"/api/cogents/test/runs/{run.id}/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["log_group"] == "CogOS session artifacts"
    assert payload["log_stream"] is not None
    assert len(payload["entries"]) == 4
    assert "trigger" in payload["entries"][0]["message"]
    assert "dispatch_failed" in payload["entries"][1]["message"]
    assert "invoke throttled" in payload["entries"][1]["message"]
    assert "final | status=failed | stop=dispatch_error" in payload["entries"][2]["message"]
    assert "manifest | latest_run=" in payload["entries"][3]["message"]


def test_run_logs_endpoint_returns_pre_turn_failure_artifacts(monkeypatch, tmp_path):
    repo = LocalRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="alpha.worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
    )
    repo.upsert_process(process)

    run = Run(id=uuid4(), process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    monkeypatch.setattr(executor_handler, "_load_includes", lambda _repo: (_ for _ in ()).throw(RuntimeError("include boom")))

    run_and_complete(
        process,
        {"payload": {"content": "hello"}},
        run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=object(),
    )

    stored_run = repo.get_run(run.id)
    assert stored_run is not None
    assert stored_run.status == RunStatus.FAILED
    assert stored_run.duration_ms is not None
    assert stored_run.snapshot is not None

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get(f"/api/cogents/test/runs/{run.id}/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["log_group"] == "CogOS session artifacts"
    assert payload["log_stream"] is not None
    assert len(payload["entries"]) == 4
    assert "trigger" in payload["entries"][0]["message"]
    assert "final_stop | stop=exception" in payload["entries"][1]["message"]
    assert "include boom" in payload["entries"][1]["message"]
    assert "final | status=failed | stop=exception" in payload["entries"][2]["message"]
    assert "manifest | latest_run=" in payload["entries"][3]["message"]


def test_run_logs_endpoint_captures_executor_logger_output(monkeypatch, tmp_path):
    repo = LocalRepository(str(tmp_path))
    process = Process(
        id=uuid4(),
        name="secret-audit/scout/manual-1735000000",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
        content="@{apps/secret-audit/config.json}\n@{apps/secret-audit/heuristics.md}",
    )
    repo.upsert_process(process)

    run = Run(id=uuid4(), process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    monkeypatch.setattr(executor_handler, "_load_includes", lambda _repo: "")

    class _Bedrock:
        def converse(self, **_kwargs):
            return {
                "output": {"message": {"role": "assistant", "content": [{"text": "done"}]}},
                "usage": {"inputTokens": 3, "outputTokens": 2},
                "stopReason": "end_turn",
            }

    run_and_complete(
        process,
        {"payload": {"content": "hello"}},
        run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=_Bedrock(),
    )

    app = create_app()
    client = TestClient(app)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        response = client.get(f"/api/cogents/test/runs/{run.id}/logs?limit=100")

    assert response.status_code == 200
    payload = response.json()
    messages = [entry["message"] for entry in payload["entries"]]
    assert any("cannot read prompt reference apps/secret-audit/config.json" in message for message in messages)
    assert any("cannot read prompt reference apps/secret-audit/heuristics.md" in message for message in messages)
