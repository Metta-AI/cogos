from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.ws import ConnectionManager


def test_manager_starts_empty():
    m = ConnectionManager()
    assert m.connection_count == 0


def test_disconnect_nonexistent():
    m = ConnectionManager()
    # Should not raise
    m.disconnect("test", None)


def test_ws_endpoint_accepts():
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/cogents/test-cogent") as ws:
        # Connection should be accepted
        ws.send_text("ping")
