"""Tests for integrations router including reveal endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_integrations_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/integrations" in routes


def test_reveal_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/integrations/{integration_name}/reveal/{field_name}" in routes


def test_reveal_rejects_non_secret_field(monkeypatch):
    """The reveal endpoint should reject non-secret fields with 400."""
    mock_sp = MagicMock()
    monkeypatch.setattr(
        "dashboard.routers.integrations._get_secrets_provider",
        lambda: mock_sp,
    )
    client = _client()
    # display_name is a text field on discord, not secret
    resp = client.get("/api/cogents/test/integrations/discord/reveal/display_name")
    assert resp.status_code == 400


def test_reveal_returns_unmasked_secret(monkeypatch):
    """The reveal endpoint should return the raw secret value."""
    mock_sp = MagicMock()
    mock_sp.get_secret.return_value = json.dumps({
        "type": "github",
        "access_token": "ghp_test123secret456",
    })
    monkeypatch.setattr(
        "dashboard.routers.integrations._get_secrets_provider",
        lambda: mock_sp,
    )
    client = _client()
    resp = client.get("/api/cogents/test/integrations/github/reveal/access_token")
    assert resp.status_code == 200
    assert "ghp_test123secret456" in resp.json()["value"]


def test_reveal_unknown_integration():
    client = _client()
    resp = client.get("/api/cogents/test/integrations/nonexistent/reveal/foo")
    assert resp.status_code == 404


def test_reveal_unknown_field(monkeypatch):
    mock_sp = MagicMock()
    monkeypatch.setattr(
        "dashboard.routers.integrations._get_secrets_provider",
        lambda: mock_sp,
    )
    client = _client()
    resp = client.get("/api/cogents/test/integrations/discord/reveal/nonexistent")
    assert resp.status_code == 404
