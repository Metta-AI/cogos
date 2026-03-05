"""Route registration tests for events, triggers, and memory routers."""


from dashboard.app import create_app


def _route_paths(app) -> list[str]:
    return [r.path for r in app.routes]


def test_events_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/events" in paths


def test_event_tree_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/events/{event_id}/tree" in paths


def test_triggers_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/triggers" in paths


def test_triggers_toggle_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/triggers/toggle" in paths


def test_memory_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/memory" in paths
