"""Tests for the session management endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from cogos_api.app import create_app
from cogos_api.auth import TokenClaims

TEST_SECRET = "test-secret-key-for-unit-tests"
TEST_EXECUTOR_KEY = "test-executor-key-12345"


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _mock_deps():
    import cogos_api.auth

    cogos_api.auth._cached_signing_key = None
    with (
        patch("cogos_api.auth._get_signing_key", return_value=TEST_SECRET),
        patch("cogos_api.auth._get_executor_key", return_value=TEST_EXECUTOR_KEY),
    ):
        cogos_api.auth._cached_signing_key = TEST_SECRET
        yield
        cogos_api.auth._cached_signing_key = None


class TestCreateSession:
    def test_valid_request(self, client):
        pid = uuid4()
        mock_repo = MagicMock()
        mock_process = MagicMock()
        mock_process.name = "test-process"
        mock_repo.get_process.return_value = mock_process

        with patch("cogos_api.routers.sessions.get_repo", return_value=mock_repo):
            resp = client.post(
                "/api/v1/sessions",
                json={"process_id": str(pid), "cogent": "alpha"},
                headers={"X-Executor-Key": TEST_EXECUTOR_KEY},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["process_id"] == str(pid)
        assert data["cogent"] == "alpha"
        assert data["expires_at"] > 0

    def test_invalid_executor_key(self, client):
        resp = client.post(
            "/api/v1/sessions",
            json={"process_id": str(uuid4()), "cogent": "alpha"},
            headers={"X-Executor-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_missing_executor_key(self, client):
        resp = client.post(
            "/api/v1/sessions",
            json={"process_id": str(uuid4()), "cogent": "alpha"},
        )
        assert resp.status_code == 403

    def test_invalid_process_id(self, client):
        resp = client.post(
            "/api/v1/sessions",
            json={"process_id": "not-a-uuid", "cogent": "alpha"},
            headers={"X-Executor-Key": TEST_EXECUTOR_KEY},
        )
        assert resp.status_code == 400

    def test_process_not_found(self, client):
        mock_repo = MagicMock()
        mock_repo.get_process.return_value = None

        with patch("cogos_api.routers.sessions.get_repo", return_value=mock_repo):
            resp = client.post(
                "/api/v1/sessions",
                json={"process_id": str(uuid4()), "cogent": "alpha"},
                headers={"X-Executor-Key": TEST_EXECUTOR_KEY},
            )
        assert resp.status_code == 404


class TestGetSessionInfo:
    def test_valid_session(self, client):
        from cogos_api.auth import create_session_token

        pid = uuid4()
        token = create_session_token(str(pid), "alpha")

        mock_repo = MagicMock()
        mock_process = MagicMock()
        mock_process.name = "my-process"
        mock_repo.get_process.return_value = mock_process
        mock_repo.list_process_capabilities.return_value = []

        with patch("cogos_api.routers.sessions.get_repo", return_value=mock_repo):
            resp = client.get(
                "/api/v1/sessions/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["process_id"] == str(pid)
        assert data["cogent"] == "alpha"
        assert data["process_name"] == "my-process"

    def test_missing_auth(self, client):
        resp = client.get("/api/v1/sessions/me")
        assert resp.status_code == 401
