from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cogtainer.lambdas.web_gateway.handler import (
    _content_type_for,
    _is_api_request,
    _make_response,
    _resolve_static_path,
)


class TestResolveStaticPath:
    def test_root(self):
        assert _resolve_static_path("/") == "web/index.html"

    def test_empty(self):
        assert _resolve_static_path("") == "web/index.html"

    def test_path(self):
        assert _resolve_static_path("/dashboard") == "web/dashboard"

    def test_nested_path(self):
        assert _resolve_static_path("/assets/style.css") == "web/assets/style.css"

    def test_index_html(self):
        assert _resolve_static_path("/index.html") == "web/index.html"


class TestIsApiRequest:
    def test_api_status(self):
        assert _is_api_request("/api/status") is True

    def test_api_root(self):
        assert _is_api_request("/api") is True

    def test_api_trailing_slash(self):
        assert _is_api_request("/api/") is True

    def test_dashboard(self):
        assert _is_api_request("/dashboard") is False

    def test_root(self):
        assert _is_api_request("/") is False

    def test_api_like(self):
        assert _is_api_request("/apiary") is False


class TestContentTypeFor:
    def test_html(self):
        assert _content_type_for("index.html") == "text/html"

    def test_htm(self):
        assert _content_type_for("page.htm") == "text/html"

    def test_js(self):
        assert _content_type_for("app.js") == "text/javascript"

    def test_mjs(self):
        assert _content_type_for("module.mjs") == "text/javascript"

    def test_css(self):
        assert _content_type_for("style.css") == "text/css"

    def test_json(self):
        assert _content_type_for("data.json") == "application/json"

    def test_svg(self):
        assert _content_type_for("icon.svg") == "image/svg+xml"

    def test_xml(self):
        assert _content_type_for("feed.xml") == "application/xml"

    def test_txt(self):
        assert _content_type_for("readme.txt") == "text/plain"

    def test_md(self):
        assert _content_type_for("readme.md") == "text/markdown"

    def test_ico(self):
        assert _content_type_for("favicon.ico") == "image/x-icon"

    def test_woff2(self):
        assert _content_type_for("font.woff2") == "font/woff2"

    def test_woff(self):
        assert _content_type_for("font.woff") == "font/woff"

    def test_unknown(self):
        assert _content_type_for("data.bin") == "application/octet-stream"

    def test_no_extension(self):
        assert _content_type_for("Makefile") == "application/octet-stream"


class TestMakeResponse:
    def test_basic(self):
        resp = _make_response(200, "ok")
        assert resp["statusCode"] == 200
        assert resp["body"] == "ok"
        assert resp["headers"]["content-type"] == "text/plain"
        assert resp["headers"]["cache-control"] == "no-store"

    def test_custom_content_type(self):
        resp = _make_response(200, "<h1>hi</h1>", content_type="text/html")
        assert resp["headers"]["content-type"] == "text/html"

    def test_extra_headers(self):
        resp = _make_response(200, "ok", headers={"x-custom": "val"})
        assert resp["headers"]["x-custom"] == "val"
        assert resp["headers"]["cache-control"] == "no-store"


class TestHandlerAuth:
    @patch("cogtainer.lambdas.web_gateway.handler._handle_static_request")
    def test_skips_jwt_when_env_set(self, mock_static):
        from cogtainer.lambdas.web_gateway.handler import handler

        mock_static.return_value = _make_response(200, "ok")
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/"}},
            "rawPath": "/",
            "queryStringParameters": {},
            "headers": {},
            "body": None,
        }
        resp = handler(event)
        assert resp["statusCode"] == 200

    @patch("cogtainer.lambdas.web_gateway.handler._validate_cf_jwt", return_value=False)
    def test_rejects_invalid_jwt(self, mock_validate):
        from cogtainer.lambdas.web_gateway.handler import handler

        old = os.environ.pop("SKIP_JWT_VALIDATION", None)
        try:
            event = {
                "requestContext": {"http": {"method": "GET", "path": "/"}},
                "rawPath": "/",
                "queryStringParameters": {},
                "headers": {"cf-access-jwt-assertion": "bad-token"},
                "body": None,
            }
            resp = handler(event)
            assert resp["statusCode"] == 403
        finally:
            if old is not None:
                os.environ["SKIP_JWT_VALIDATION"] = old


class TestHandlerStaticRequest:
    @patch("cogtainer.lambdas.web_gateway.handler.FileStore")
    def test_serves_static_file(self, mock_store_cls):
        from cogtainer.lambdas.web_gateway.handler import _handle_static_request

        mock_repo = MagicMock()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        mock_store.get_content.return_value = "<html>hello</html>"

        resp = _handle_static_request(mock_repo, "/index.html")
        assert resp["statusCode"] == 200
        assert resp["body"] == "<html>hello</html>"
        assert resp["headers"]["content-type"] == "text/html"
        mock_store.get_content.assert_called_with("web/index.html")

    @patch("cogtainer.lambdas.web_gateway.handler.FileStore")
    def test_fallback_index_html(self, mock_store_cls):
        from cogtainer.lambdas.web_gateway.handler import _handle_static_request

        mock_repo = MagicMock()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        mock_store.get_content.side_effect = [None, "<html>index</html>"]

        resp = _handle_static_request(mock_repo, "/dashboard")
        assert resp["statusCode"] == 200
        assert resp["body"] == "<html>index</html>"
        assert resp["headers"]["content-type"] == "text/html"
        calls = mock_store.get_content.call_args_list
        assert calls[0].args[0] == "web/dashboard"
        assert calls[1].args[0] == "web/dashboard/index.html"

    @patch("cogtainer.lambdas.web_gateway.handler.FileStore")
    def test_returns_404(self, mock_store_cls):
        from cogtainer.lambdas.web_gateway.handler import _handle_static_request

        mock_repo = MagicMock()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        mock_store.get_content.return_value = None

        resp = _handle_static_request(mock_repo, "/nonexistent.html")
        assert resp["statusCode"] == 404

    @patch("cogtainer.lambdas.web_gateway.handler.FileStore")
    def test_extensionless_html_serves_text_html(self, mock_store_cls):
        from cogtainer.lambdas.web_gateway.handler import _handle_static_request

        mock_repo = MagicMock()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        mock_store.get_content.return_value = "<html>hello</html>"

        resp = _handle_static_request(mock_repo, "/nature-fact")
        assert resp["statusCode"] == 200
        assert resp["body"] == "<html>hello</html>"
        assert resp["headers"]["content-type"] == "text/html"


class TestHandlerBinaryStatic:
    @patch("cogtainer.lambdas.web_gateway.handler.FileStore")
    def test_serves_base64_file(self, mock_store_cls):
        from cogtainer.lambdas.web_gateway.handler import _handle_static_request

        mock_repo = MagicMock()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        mock_store.get_content.return_value = "base64:iVBORw0KGgo="

        resp = _handle_static_request(mock_repo, "/image.png")
        assert resp["statusCode"] == 200
        assert resp["body"] == "iVBORw0KGgo="
        assert resp["isBase64Encoded"] is True
        assert resp["headers"]["content-type"] == "image/png"

    @patch("cogtainer.lambdas.web_gateway.handler.FileStore")
    def test_serves_regular_file_unchanged(self, mock_store_cls):
        from cogtainer.lambdas.web_gateway.handler import _handle_static_request

        mock_repo = MagicMock()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        mock_store.get_content.return_value = "<html>hello</html>"

        resp = _handle_static_request(mock_repo, "/index.html")
        assert resp["statusCode"] == 200
        assert resp.get("isBase64Encoded") is not True


class TestHandlerApiRequest:
    @patch("cogtainer.lambdas.web_gateway.handler.boto3")
    def test_returns_503_no_channel(self, mock_boto):
        from cogtainer.lambdas.web_gateway.handler import _handle_api_request

        mock_repo = MagicMock()
        mock_repo.get_channel_by_name.return_value = None

        resp = _handle_api_request(mock_repo, "GET", "/api/status", {}, {}, None)
        assert resp["statusCode"] == 503

    @patch("cogtainer.lambdas.web_gateway.handler.boto3")
    def test_returns_503_no_handler(self, mock_boto):
        from cogtainer.lambdas.web_gateway.handler import _handle_api_request

        mock_repo = MagicMock()
        channel = MagicMock()
        channel.id = uuid4()
        mock_repo.get_channel_by_name.return_value = channel
        mock_repo.match_handlers_by_channel.return_value = []

        resp = _handle_api_request(mock_repo, "GET", "/api/status", {}, {}, None)
        assert resp["statusCode"] == 503

    @patch("cogtainer.lambdas.web_gateway.handler.boto3")
    def test_successful_api_call(self, mock_boto):
        from cogtainer.lambdas.web_gateway.handler import _handle_api_request

        mock_repo = MagicMock()

        channel = MagicMock()
        channel.id = uuid4()
        mock_repo.get_channel_by_name.return_value = channel

        handler_obj = MagicMock()
        handler_obj.process = uuid4()
        mock_repo.match_handlers_by_channel.return_value = [handler_obj]

        process = MagicMock()
        process.id = handler_obj.process
        mock_repo.get_process.return_value = process

        web_response = {"status": 200, "headers": {}, "body": '{"ok": true}'}
        lambda_client = MagicMock()
        lambda_response = {
            "StatusCode": 200,
            "Payload": MagicMock(read=MagicMock(return_value=json.dumps({"web_response": web_response}).encode())),
        }
        lambda_client.invoke.return_value = lambda_response
        mock_boto.client.return_value = lambda_client

        resp = _handle_api_request(mock_repo, "GET", "/api/status", {}, {"host": "example.com"}, None)
        assert resp["statusCode"] == 200
        assert resp["body"] == '{"ok": true}'

    @patch("cogtainer.lambdas.web_gateway.handler.boto3")
    def test_filters_cf_headers(self, mock_boto):
        from cogtainer.lambdas.web_gateway.handler import _handle_api_request

        mock_repo = MagicMock()

        channel = MagicMock()
        channel.id = uuid4()
        mock_repo.get_channel_by_name.return_value = channel

        handler_obj = MagicMock()
        handler_obj.process = uuid4()
        mock_repo.match_handlers_by_channel.return_value = [handler_obj]

        process = MagicMock()
        process.id = handler_obj.process
        mock_repo.get_process.return_value = process

        web_response = {"status": 200, "headers": {}, "body": "ok"}
        lambda_client = MagicMock()
        lambda_response = {
            "StatusCode": 200,
            "Payload": MagicMock(read=MagicMock(return_value=json.dumps({"web_response": web_response}).encode())),
        }
        lambda_client.invoke.return_value = lambda_response
        mock_boto.client.return_value = lambda_client

        _handle_api_request(
            mock_repo, "POST", "/api/data", {}, {"host": "example.com", "cf-access-jwt-assertion": "secret"}, "body"
        )

        call_args = mock_repo.append_channel_message.call_args
        msg = call_args.args[0]
        forwarded_headers = msg.payload["headers"]
        assert "cf-access-jwt-assertion" not in forwarded_headers
        assert "host" in forwarded_headers
