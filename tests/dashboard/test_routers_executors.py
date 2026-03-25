"""Tests for dashboard executor API endpoints."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import Executor, ExecutorStatus, ExecutorToken
from dashboard.app import create_app


class _ExecutorRepoStub:
    """Minimal repo stub for executor API tests."""

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._token_hash = hashlib.sha256(b"test-token-secret").hexdigest()
        self._token = ExecutorToken(
            id=uuid4(),
            name="test-pool",
            token_hash=self._token_hash,
            scope="executor",
            created_at=now,
        )
        self._executor = Executor(
            id=uuid4(),
            executor_id="executor-test-abc123",
            channel_type="claude-code",
            executor_tags=["claude-code", "git"],
            metadata={"machine": "test-host"},
            status=ExecutorStatus.IDLE,
            last_heartbeat_at=now,
            registered_at=now,
        )
        self._executors: dict[str, Executor] = {
            self._executor.executor_id: self._executor,
        }
        self._completed_runs: list[dict] = []

    def get_executor_token_by_hash(self, token_hash: str) -> ExecutorToken | None:
        if token_hash == self._token_hash:
            return self._token
        return None

    def register_executor(self, executor: Executor) -> str:
        self._executors[executor.executor_id] = executor
        return str(executor.id)

    def get_channel_by_name(self, name: str):
        return None

    def upsert_channel(self, channel):
        pass

    def get_executor(self, executor_id: str) -> Executor | None:
        return self._executors.get(executor_id)

    def list_executors(self, status=None) -> list[Executor]:
        executors = list(self._executors.values())
        if status:
            executors = [e for e in executors if e.status == status]
        return executors

    def update_executor_status(self, executor_id: str, status, current_run_id=None):
        e = self._executors.get(executor_id)
        if e:
            e.status = status
            e.current_run_id = current_run_id

    def delete_executor(self, executor_id: str):
        self._executors.pop(executor_id, None)

    def heartbeat_executor(self, executor_id, status=None, current_run_id=None, resource_usage=None):
        return executor_id in self._executors

    def complete_run(self, run_id, *, status, error=None, tokens_in=0, tokens_out=0, duration_ms=None):
        self._completed_runs.append({
            "run_id": run_id, "status": status, "error": error,
        })
        return True


_BEARER = "Bearer test-token-secret"


def _client_and_repo():
    app = create_app()
    client = TestClient(app)
    repo = _ExecutorRepoStub()
    return client, repo


def _patches(repo):
    """Return a context manager that patches both dashboard and auth get_repo."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("dashboard.routers.executors.get_repo", return_value=repo))
    stack.enter_context(patch("cogos.api.auth.get_repo", return_value=repo))
    return stack


def test_list_executors():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.get("/api/cogents/test/executors")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["executors"][0]["executor_id"] == "executor-test-abc123"


def test_list_executors_filter_by_status():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.get("/api/cogents/test/executors?status=busy")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_get_executor():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.get("/api/cogents/test/executors/executor-test-abc123")
    assert response.status_code == 200
    assert response.json()["executor_id"] == "executor-test-abc123"
    assert response.json()["executor_tags"] == ["claude-code", "git"]


def test_get_executor_not_found():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.get("/api/cogents/test/executors/no-such")
    assert response.status_code == 404


def test_register_executor_requires_auth():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post(
            "/api/cogents/test/executors/register",
            json={"executor_id": "exec-new"},
        )
    assert response.status_code == 401


def test_register_executor_with_valid_token():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post(
            "/api/cogents/test/executors/register",
            json={
                "executor_id": "exec-new",
                "executor_tags": ["claude-code", "filesystem"],
            },
            headers={"Authorization": _BEARER},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["executor_id"] == "exec-new"
    assert data["status"] == "registered"
    assert data["heartbeat_interval_s"] == 30


def test_register_executor_with_bad_token():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post(
            "/api/cogents/test/executors/register",
            json={"executor_id": "exec-bad"},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert response.status_code == 401


def test_heartbeat():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post(
            "/api/cogents/test/executors/executor-test-abc123/heartbeat",
            json={"status": "idle"},
            headers={"Authorization": _BEARER},
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_heartbeat_requires_auth():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post(
            "/api/cogents/test/executors/executor-test-abc123/heartbeat",
            json={"status": "idle"},
        )
    assert response.status_code == 401


def test_heartbeat_not_found():
    client, repo = _client_and_repo()
    repo._executors.clear()
    with _patches(repo):
        response = client.post(
            "/api/cogents/test/executors/no-such/heartbeat",
            json={"status": "idle"},
            headers={"Authorization": _BEARER},
        )
    assert response.status_code == 404


def test_drain_executor():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post("/api/cogents/test/executors/executor-test-abc123/drain")
    assert response.status_code == 200
    assert response.json()["status"] == "stale"
    assert repo._executors["executor-test-abc123"].status == ExecutorStatus.STALE


def test_drain_not_found():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.post("/api/cogents/test/executors/no-such/drain")
    assert response.status_code == 404


def test_remove_executor():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.delete("/api/cogents/test/executors/executor-test-abc123")
    assert response.status_code == 200
    assert "executor-test-abc123" not in repo._executors


def test_remove_not_found():
    client, repo = _client_and_repo()
    with _patches(repo):
        response = client.delete("/api/cogents/test/executors/no-such")
    assert response.status_code == 404


def test_complete_run():
    client, repo = _client_and_repo()
    run_id = str(uuid4())
    with _patches(repo):
        response = client.post(
            f"/api/cogents/test/runs/{run_id}/complete",
            json={
                "executor_id": "executor-test-abc123",
                "status": "completed",
                "tokens_used": {"input": 1500, "output": 800},
                "duration_ms": 45000,
            },
            headers={"Authorization": _BEARER},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] == "completed"
    # Executor should be back to idle
    assert repo._executors["executor-test-abc123"].status == ExecutorStatus.IDLE
    # Run should have been completed
    assert len(repo._completed_runs) == 1


def test_complete_run_requires_auth():
    client, repo = _client_and_repo()
    run_id = str(uuid4())
    with _patches(repo):
        response = client.post(
            f"/api/cogents/test/runs/{run_id}/complete",
            json={
                "executor_id": "executor-test-abc123",
                "status": "failed",
                "error": "something went wrong",
            },
        )
    assert response.status_code == 401
