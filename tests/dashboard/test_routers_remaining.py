"""Tests for channels, resources, cron, and setup routers."""

from fastapi.testclient import TestClient

from dashboard.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_channels_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/channels" in routes


def test_channel_send_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/channels/{channel_id}/messages" in routes


def test_resources_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/resources" in routes


def test_cron_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/cron" in routes


def test_schemas_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/api/cogents/{name}/schemas" in routes
