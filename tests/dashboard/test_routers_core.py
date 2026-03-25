"""Tests for cogos-status, processes, and runs routers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_cogos_status_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/cogos-status")
    assert resp.status_code != 404


def test_processes_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/process")
    assert resp.status_code != 404


def test_runs_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/runs")
    assert resp.status_code != 404


def test_message_traces_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/message-traces")
    assert resp.status_code != 404


def test_cogos_status_with_mock_repo():
    mock_repo = MagicMock()
    mock_repo.list_processes.return_value = []
    mock_repo.list_files.return_value = []
    mock_repo.list_capabilities.return_value = []
    mock_repo.list_channels.return_value = []
    mock_repo.list_runs.return_value = []
    mock_repo.get_meta.return_value = None
    with patch("dashboard.routers.cogos_status.get_repo", return_value=mock_repo):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/cogos-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["processes"]["total"] == 0


def test_processes_with_mock_repo():
    mock_repo = MagicMock()
    mock_repo.query.return_value = []
    with patch("dashboard.routers.processes.get_repo", return_value=mock_repo):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/process")
        assert resp.status_code == 200
