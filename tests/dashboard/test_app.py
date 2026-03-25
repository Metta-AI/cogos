from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.app import create_app


def test_healthz():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_lifespan_warms_db():
    """Dashboard startup should pre-warm DB connection via get_repo()."""
    fake_repo = MagicMock()
    with patch("cogos.api.db.get_repo", return_value=fake_repo) as mock_get_repo:
        app = create_app()
        with TestClient(app):
            pass  # triggers lifespan

    mock_get_repo.assert_called()


def test_web_static_extensionless_html_renders_in_browser():
    app = create_app()
    client = TestClient(app)

    with patch("cogos.files.store.FileStore.get_content", return_value="<html>hello</html>"), patch(
        "cogos.api.db.get_repo", return_value=MagicMock()
    ):
        resp = client.get("/web/static/nature-fact")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == "<html>hello</html>"


def test_web_static_falls_back_to_directory_index():
    app = create_app()
    client = TestClient(app)

    with patch(
        "cogos.files.store.FileStore.get_content",
        side_effect=[None, "<html>nested</html>"],
    ) as mock_get_content, patch("cogos.api.db.get_repo", return_value=MagicMock()):
        resp = client.get("/web/static/nature-fact")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == "<html>nested</html>"
    calls = mock_get_content.call_args_list
    assert calls[0].args[0] == "web/nature-fact"
    assert calls[1].args[0] == "web/nature-fact/index.html"


def test_web_static_decodes_base64_assets():
    app = create_app()
    client = TestClient(app)

    with patch("cogos.files.store.FileStore.get_content", return_value="base64:iVBORw0KGgo="), patch(
        "cogos.api.db.get_repo", return_value=MagicMock()
    ):
        resp = client.get("/web/static/image.png")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content == b"\x89PNG\r\n\x1a\n"
