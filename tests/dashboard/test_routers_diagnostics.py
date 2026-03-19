"""Tests for the diagnostics router."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _mock_repo():
    mock = MagicMock()
    mock.query.return_value = []
    mock.query_one.return_value = None
    return mock


def test_diagnostics_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/diagnostics" in routes


def test_diagnostics_history_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/diagnostics/history" in routes


def test_diagnostics_history_no_data():
    mock = _mock_repo()
    with (
        patch("dashboard.routers.diagnostics.get_repo", return_value=mock),
        patch("dashboard.routers.diagnostics.FileStore") as MockFS,
    ):
        MockFS.return_value.history.return_value = []
        client = _client()
        resp = client.get("/api/cogents/test/diagnostics/history")
    assert resp.status_code == 200
    assert resp.json() == {"runs": []}


def test_diagnostics_history_returns_parsed_versions():
    mock = _mock_repo()
    v1 = MagicMock()
    v1.version = 1
    v1.content = '{"timestamp":"2026-03-01T00:00:00Z","summary":{"total":2,"pass":2,"fail":0},"categories":{}}'
    v2 = MagicMock()
    v2.version = 2
    v2.content = '{"timestamp":"2026-03-02T00:00:00Z","summary":{"total":2,"pass":1,"fail":1},"categories":{}}'

    with (
        patch("dashboard.routers.diagnostics.get_repo", return_value=mock),
        patch("dashboard.routers.diagnostics.FileStore") as MockFS,
    ):
        MockFS.return_value.history.return_value = [v1, v2]
        client = _client()
        resp = client.get("/api/cogents/test/diagnostics/history?limit=10")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runs"]) == 2
    # Newest first
    assert data["runs"][0]["timestamp"] == "2026-03-02T00:00:00Z"
    assert data["runs"][1]["timestamp"] == "2026-03-01T00:00:00Z"


def test_diagnostics_history_skips_invalid_json():
    mock = _mock_repo()
    v1 = MagicMock()
    v1.version = 1
    v1.content = "not valid json"
    v2 = MagicMock()
    v2.version = 2
    v2.content = '{"timestamp":"2026-03-02T00:00:00Z","summary":{"total":1,"pass":1,"fail":0},"categories":{}}'

    with (
        patch("dashboard.routers.diagnostics.get_repo", return_value=mock),
        patch("dashboard.routers.diagnostics.FileStore") as MockFS,
    ):
        MockFS.return_value.history.return_value = [v1, v2]
        client = _client()
        resp = client.get("/api/cogents/test/diagnostics/history")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runs"]) == 1


def test_diagnostics_history_respects_limit():
    mock = _mock_repo()
    versions = []
    for i in range(5):
        v = MagicMock()
        v.version = i + 1
        v.content = (
            f'{{"timestamp":"2026-03-0{i + 1}T00:00:00Z","summary":{{"total":1,"pass":1,"fail":0}},"categories":{{}}}}'
        )
        versions.append(v)

    with (
        patch("dashboard.routers.diagnostics.get_repo", return_value=mock),
        patch("dashboard.routers.diagnostics.FileStore") as MockFS,
    ):
        MockFS.return_value.history.return_value = versions
        client = _client()
        resp = client.get("/api/cogents/test/diagnostics/history?limit=3")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runs"]) == 3
