"""Tests for tasks, channels, alerts, and resources routers."""

from fastapi.testclient import TestClient

from dashboard.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_tasks_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]
    assert "/api/cogents/{name}/tasks" in routes


def test_task_detail_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]
    assert "/api/cogents/{name}/tasks/{task_id}" in routes


def test_channels_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]
    assert "/api/cogents/{name}/channels" in routes


def test_alerts_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]
    assert "/api/cogents/{name}/alerts" in routes


def test_resources_route_registered():
    client = _client()
    routes = [r.path for r in client.app.routes]
    assert "/api/cogents/{name}/resources" in routes
