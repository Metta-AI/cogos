"""Tests for the capability proxy API endpoints."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.api.app import create_app
from cogos.api.auth import AuthContext
from cogos.db.models import ExecutorToken


# ── Test capability ──────────────────────────────────────────


class QueryResult(BaseModel):
    rows: list[dict]
    count: int


class DummyDataCapability(Capability):
    """Test data capability."""

    def _narrow(self, existing: dict, requested: dict) -> dict:
        return {**existing, **requested}

    def query(self, sql: str, params: dict | None = None) -> QueryResult:
        """Execute a query."""
        return QueryResult(rows=[{"id": 1, "name": "test"}], count=1)

    def write(self, table: str, data: dict) -> dict:
        """Write a row."""
        return {"ok": True, "table": table}


# ── Fixtures ─────────────────────────────────────────────────

PROCESS_ID = str(uuid4())
RAW_TOKEN = "test-token-for-caps"
TOKEN_HASH = hashlib.sha256(RAW_TOKEN.encode()).hexdigest()
AUTH = AuthContext(token_name="test-pool", process_id=PROCESS_ID)


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _mock_deps():
    mock_repo = MagicMock()
    cap = DummyDataCapability(mock_repo, uuid4())
    mock_repo.get_executor_token_by_hash.side_effect = (
        lambda h: ExecutorToken(name="test-pool", token_hash=h) if h == TOKEN_HASH else None
    )

    with (
        patch("cogos.api.auth.get_repo", return_value=mock_repo),
        patch("cogos.api.routers.capabilities._get_proxies", return_value={"data": cap}),
    ):
        yield


def _auth_headers():
    return {
        "Authorization": f"Bearer {RAW_TOKEN}",
        "X-Process-Id": PROCESS_ID,
    }


# ── Tests ────────────────────────────────────────────────────


class TestListCapabilities:
    def test_returns_capabilities(self, client):
        resp = client.get("/api/v1/capabilities", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["capabilities"]) == 1
        assert data["capabilities"][0]["name"] == "data"
        assert "query" in data["capabilities"][0]["methods"]
        assert "write" in data["capabilities"][0]["methods"]


class TestGetCapability:
    def test_found(self, client):
        resp = client.get("/api/v1/capabilities/data", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["name"] == "data"

    def test_not_found(self, client):
        with patch("cogos.api.routers.capabilities._get_proxies", return_value={}):
            resp = client.get("/api/v1/capabilities/missing", headers=_auth_headers())
            assert resp.status_code == 404


class TestListMethods:
    def test_returns_methods(self, client):
        resp = client.get("/api/v1/capabilities/data/methods", headers=_auth_headers())
        assert resp.status_code == 200
        methods = resp.json()
        names = [m["name"] for m in methods]
        assert "query" in names
        assert "write" in names

    def test_method_has_params(self, client):
        resp = client.get("/api/v1/capabilities/data/methods", headers=_auth_headers())
        methods = {m["name"]: m for m in resp.json()}
        query = methods["query"]
        param_names = [p["name"] for p in query["params"]]
        assert "sql" in param_names


class TestInvokeMethod:
    def test_invoke_query(self, client):
        resp = client.post(
            "/api/v1/capabilities/data/query",
            json={"args": {"sql": "SELECT 1"}},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is None
        assert data["result"]["count"] == 1
        assert data["result"]["rows"] == [{"id": 1, "name": "test"}]

    def test_invoke_write(self, client):
        resp = client.post(
            "/api/v1/capabilities/data/write",
            json={"args": {"table": "users", "data": {"name": "alice"}}},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["ok"] is True

    def test_invoke_missing_method(self, client):
        resp = client.post(
            "/api/v1/capabilities/data/nonexistent",
            json={"args": {}},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    def test_invoke_private_method_blocked(self, client):
        resp = client.post(
            "/api/v1/capabilities/data/_narrow",
            json={"args": {}},
            headers=_auth_headers(),
        )
        assert resp.status_code == 403

    def test_invoke_bad_args(self, client):
        resp = client.post(
            "/api/v1/capabilities/data/query",
            json={"args": {"wrong_param": "value"}},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is not None


class TestInvokeWithScope:
    def test_scope_applied(self, client):
        resp = client.post(
            "/api/v1/capabilities/data/query",
            json={"args": {"sql": "SELECT 1"}, "scope": {"table": "users"}},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is None


class TestAuthRequired:
    def test_missing_auth_returns_401(self, client):
        resp = client.get("/api/v1/capabilities")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.get(
            "/api/v1/capabilities",
            headers={"Authorization": "Bearer wrong-token", "X-Process-Id": PROCESS_ID},
        )
        assert resp.status_code == 401
