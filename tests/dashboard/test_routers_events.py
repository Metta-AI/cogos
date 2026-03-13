"""Route registration tests for triggers and memory routers."""


from dashboard.app import create_app


def _route_paths(app) -> list[str]:
    return [r.path for r in app.routes]


def test_cron_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/cron" in paths


def test_channels_route_registered():
    app = create_app()
    paths = _route_paths(app)
    assert "/api/cogents/{name}/channels" in paths
