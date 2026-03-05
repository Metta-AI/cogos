from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.app import create_app


def _mock_repo():
    """Create a mock repo that returns empty results for all queries."""
    mock = MagicMock()
    mock.query.return_value = []
    mock.query_one.return_value = None
    mock.execute.return_value = 0
    return mock


def test_all_rest_endpoints_registered():
    """Verify every REST endpoint is routed (not 404)."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    endpoints = [
        ("GET", "/api/cogents/test/status?range=1h"),
        ("GET", "/api/cogents/test/programs"),
        ("GET", "/api/cogents/test/sessions"),
        ("GET", "/api/cogents/test/events?range=1h"),
        ("GET", "/api/cogents/test/triggers"),
        ("GET", "/api/cogents/test/memory"),
        ("GET", "/api/cogents/test/tasks"),
        ("GET", "/api/cogents/test/channels"),
        ("GET", "/api/cogents/test/alerts"),
        ("GET", "/api/cogents/test/resources"),
    ]

    for method, path in endpoints:
        resp = client.request(method, path)
        assert resp.status_code != 404, f"{method} {path} returned 404"
        assert resp.status_code != 405, f"{method} {path} returned 405"


def test_healthz():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_websocket_endpoint():
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/cogents/test") as ws:
        ws.send_text("ping")


def test_trigger_toggle_endpoint():
    """POST endpoint exists and accepts JSON body."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/cogents/test/triggers/toggle",
        json={"ids": [], "enabled": True},
    )
    assert resp.status_code != 404
    assert resp.status_code != 405


def test_status_returns_data_with_mock():
    """Status endpoint returns correct data when repo is mocked."""
    mock = _mock_repo()
    mock.query_one.return_value = {
        "active_sessions": 0,
        "total_conversations": 0,
        "trigger_count": 0,
        "unresolved_alerts": 0,
        "recent_events": 0,
    }
    with patch("dashboard.routers.status.get_repo", return_value=mock):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cogent_name"] == "test"
        assert data["active_sessions"] == 0


def test_alerts_returns_data_with_mock():
    mock = _mock_repo()
    with patch("dashboard.routers.alerts.get_repo", return_value=mock):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/alerts")
        assert resp.status_code == 200
        assert resp.json()["alerts"] == []


def test_channels_returns_data_with_mock():
    mock = _mock_repo()
    with patch("dashboard.routers.channels.get_repo", return_value=mock):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/channels")
        assert resp.status_code == 200
        assert resp.json()["channels"] == []
