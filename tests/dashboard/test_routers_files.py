"""Tests for the dashboard files router."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cogos.db.models import File
from dashboard.app import create_app


def _file(key: str) -> File:
    now = datetime.now(UTC)
    return File(
        id=uuid4(),
        key=key,
        includes=[],
        created_at=now,
        updated_at=now,
    )


def test_files_route_uses_high_default_limit():
    mock_repo = MagicMock()
    with (
        patch("dashboard.routers.files.get_repo", return_value=mock_repo),
        patch(
            "dashboard.routers.files.FileStore.list_files",
            return_value=[_file("apps/newsfromthefront/researcher.md")],
        ) as mock_list_files,
    ):
        client = TestClient(create_app())
        response = client.get("/api/cogents/test/files")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    mock_list_files.assert_called_once_with(prefix=None, limit=5000)


def test_files_route_honors_limit_query_param():
    mock_repo = MagicMock()
    with (
        patch("dashboard.routers.files.get_repo", return_value=mock_repo),
        patch(
            "dashboard.routers.files.FileStore.list_files",
            return_value=[_file("whoami/index.md")],
        ) as mock_list_files,
    ):
        client = TestClient(create_app())
        response = client.get("/api/cogents/test/files?limit=42")

    assert response.status_code == 200
    mock_list_files.assert_called_once_with(prefix=None, limit=42)
