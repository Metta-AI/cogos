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
        ("GET", "/api/cogents/test/cogos-status"),
        ("GET", "/api/cogents/test/process"),
        ("GET", "/api/cogents/test/runs"),
        ("GET", "/api/cogents/test/message-traces"),
        ("GET", "/api/cogents/test/channels"),
        ("POST", "/api/cogents/test/channels/00000000-0000-0000-0000-000000000000/messages"),
        ("GET", "/api/cogents/test/resources"),
        ("GET", "/api/cogents/test/cron"),
        ("GET", "/api/cogents/test/schemas"),
        ("GET", "/api/cogents/test/capabilities"),
        ("GET", "/api/cogents/test/files"),
        ("GET", "/api/cogents/test/handlers"),
        ("GET", "/api/cogents/test/setup"),
        ("GET", "/api/cogents/test/diagnostics"),
        ("GET", "/api/cogents/test/diagnostics/history"),
        ("POST", "/api/cogents/test/diagnostics/run"),
        ("GET", "/api/cogents/test/integrations"),
        ("GET", "/api/cogents/test/executors"),
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


def test_cron_toggle_endpoint():
    """POST endpoint exists and accepts JSON body."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/cogents/test/cron/toggle",
        json={"ids": [], "enabled": True},
    )
    assert resp.status_code != 404
    assert resp.status_code != 405


def test_channels_returns_data_with_mock():
    mock = _mock_repo()
    with patch("dashboard.routers.channels.get_repo", return_value=mock):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/channels")
        assert resp.status_code == 200
        assert resp.json()["channels"] == []
