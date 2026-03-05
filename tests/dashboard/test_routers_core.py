"""Tests for status, programs, and sessions routers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app

# ---------------------------------------------------------------------------
# Route registration tests (no DB required)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_status_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/status")
    assert resp.status_code != 404


def test_programs_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/programs")
    assert resp.status_code != 404


def test_program_executions_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/programs/my-skill/executions")
    assert resp.status_code != 404


def test_sessions_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/sessions")
    assert resp.status_code != 404


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

def test_status_interval_mapping():
    from dashboard.routers.status import _interval
    assert _interval("1m") == "1 minute"
    assert _interval("10m") == "10 minutes"
    assert _interval("1h") == "1 hour"
    assert _interval("24h") == "24 hours"
    assert _interval("1w") == "7 days"
    assert _interval("unknown") == "1 hour"


def test_try_parse_json_programs():
    from dashboard.routers.programs import _try_parse_json
    assert _try_parse_json(None) is None
    assert _try_parse_json({"a": 1}) == {"a": 1}
    assert _try_parse_json([1, 2]) == [1, 2]
    assert _try_parse_json('{"b": 2}') == {"b": 2}
    assert _try_parse_json("not-json") == "not-json"
    assert _try_parse_json(42) == 42


def test_try_parse_json_sessions():
    from dashboard.routers.sessions import _try_parse_json
    assert _try_parse_json(None) is None
    assert _try_parse_json({"a": 1}) == {"a": 1}
    assert _try_parse_json('{"b": 2}') == {"b": 2}
    assert _try_parse_json("bad") == "bad"


# ---------------------------------------------------------------------------
# Mock-based API tests
# ---------------------------------------------------------------------------

def test_status_with_mock_repo():
    mock_repo = MagicMock()
    mock_repo.query_one.return_value = {
        "active_sessions": 2,
        "total_conversations": 5,
        "trigger_count": 3,
        "unresolved_alerts": 1,
        "recent_events": 10,
    }
    with patch("dashboard.routers.status.get_repo", return_value=mock_repo):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_sessions"] == 2
        assert data["cogent_name"] == "test"


def test_programs_with_mock_repo():
    mock_repo = MagicMock()
    mock_repo.query.side_effect = [
        [],  # run stats
        [{"name": "code-review", "program_type": "markdown",
          "description": "Review code", "sla": "{}", "triggers": "[]"}],
    ]
    with patch("dashboard.routers.programs.get_repo", return_value=mock_repo):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/cogents/test/programs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["programs"][0]["name"] == "code-review"
