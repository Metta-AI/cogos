"""Route registration tests for current trace and channel routers."""


from dashboard.app import create_app


def _route_paths(app) -> list[str]:
    return [r.path for r in app.routes]


def test_trace_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/message-traces" in paths


def test_request_flow_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/request-flows" in paths


def test_channels_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/channels" in paths
