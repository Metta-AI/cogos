"""Tests for the HTTP capability client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogos.capabilities.http_client import HttpCapabilityClient, HttpCapabilityProxy


class TestHttpCapabilityProxy:
    def test_repr(self):
        proxy = HttpCapabilityProxy("http://localhost:8200", "token", "data")
        assert "data" in repr(proxy)

    def test_private_attr_raises(self):
        proxy = HttpCapabilityProxy("http://localhost:8200", "token", "data")
        with pytest.raises(AttributeError):
            proxy._secret  # noqa: B018

    @patch("cogos.capabilities.http_client.httpx.post")
    def test_method_call(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"rows": [{"id": 1}]}, "error": None}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        proxy = HttpCapabilityProxy("http://localhost:8200", "tok", "data", "proc-123")
        result = proxy.query(sql="SELECT 1")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/api/v1/capabilities/data/query" in call_args[0][0]
        assert call_args[1]["json"]["args"] == {"sql": "SELECT 1"}
        # Verify X-Process-Id header is sent
        assert call_args[1]["headers"]["X-Process-Id"] == "proc-123"
        assert result == {"rows": [{"id": 1}]}

    @patch("cogos.capabilities.http_client.httpx.post")
    def test_method_call_no_process_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": "ok", "error": None}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        proxy = HttpCapabilityProxy("http://localhost:8200", "tok", "data")
        proxy.query(sql="SELECT 1")

        call_args = mock_post.call_args
        assert "X-Process-Id" not in call_args[1]["headers"]

    @patch("cogos.capabilities.http_client.httpx.post")
    def test_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": None, "error": "Permission denied"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        proxy = HttpCapabilityProxy("http://localhost:8200", "tok", "data")
        with pytest.raises(RuntimeError, match="Permission denied"):
            proxy.query(sql="DROP TABLE")


class TestHttpCapabilityClient:
    def test_get_returns_proxy(self):
        client = HttpCapabilityClient("http://localhost:8200", "token")
        proxy = client.get("data")
        assert isinstance(proxy, HttpCapabilityProxy)

    def test_get_caches_proxy(self):
        client = HttpCapabilityClient("http://localhost:8200", "token")
        p1 = client.get("data")
        p2 = client.get("data")
        assert p1 is p2

    def test_repr(self):
        client = HttpCapabilityClient("http://localhost:8200", "token")
        assert "localhost:8200" in repr(client)

    def test_from_token(self):
        client = HttpCapabilityClient.from_token(
            api_url="http://localhost:8200",
            token="my-token",
            process_id="proc-123",
        )
        assert isinstance(client, HttpCapabilityClient)
        assert client._token == "my-token"
        assert client._process_id == "proc-123"

    def test_from_token_proxy_has_process_id(self):
        client = HttpCapabilityClient.from_token(
            api_url="http://localhost:8200",
            token="my-token",
            process_id="proc-123",
        )
        proxy = client.get("data")
        assert proxy._process_id == "proc-123"

    @patch("cogos.capabilities.http_client.httpx.get")
    def test_list_capabilities(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"capabilities": [{"name": "data"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = HttpCapabilityClient("http://localhost:8200", "token", "proc-123")
        caps = client.list_capabilities()
        assert len(caps) == 1
        assert caps[0]["name"] == "data"
        # Verify X-Process-Id header is sent
        call_args = mock_get.call_args
        assert call_args[1]["headers"]["X-Process-Id"] == "proc-123"
