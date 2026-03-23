"""Tests for cogos.api.auth -- ExecutorToken validation."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from cogos.api.auth import AuthContext, validate_token
from cogos.db.models import ExecutorToken


def _make_request(headers: dict[str, str] | None = None) -> MagicMock:
    """Build a fake FastAPI Request with the given headers."""
    _headers = headers or {}
    mock_headers = MagicMock()
    mock_headers.get = lambda key, default="": _headers.get(key, default)
    request = MagicMock()
    request.headers = mock_headers
    return request


def _mock_repo(token_name: str = "test-pool", raw_token: str = "test-token-123"):
    """Return a mock repo that recognises the given raw token."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    repo = MagicMock()
    stored = ExecutorToken(name=token_name, token_hash=token_hash)
    repo.get_executor_token_by_hash.side_effect = (
        lambda h: stored if h == token_hash else None
    )
    return repo


class TestValidateToken:
    def test_valid_bearer_token(self):
        repo = _mock_repo()
        request = _make_request({"authorization": "Bearer test-token-123"})
        with patch("cogos.api.auth.get_repo", return_value=repo):
            ctx = validate_token(request)
        assert isinstance(ctx, AuthContext)
        assert ctx.token_name == "test-pool"
        assert ctx.process_id == ""

    def test_valid_bearer_with_process_id(self):
        repo = _mock_repo()
        request = _make_request({
            "authorization": "Bearer test-token-123",
            "x-process-id": "proc-abc",
        })
        with patch("cogos.api.auth.get_repo", return_value=repo):
            ctx = validate_token(request)
        assert ctx.process_id == "proc-abc"

    def test_x_api_key_header(self):
        repo = _mock_repo()
        request = _make_request({"x-api-key": "test-token-123"})
        with patch("cogos.api.auth.get_repo", return_value=repo):
            ctx = validate_token(request)
        assert ctx.token_name == "test-pool"

    def test_missing_token_raises_401(self):
        request = _make_request({})
        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)
        assert exc_info.value.status_code == 401
        assert "Missing" in exc_info.value.detail

    def test_invalid_token_raises_401(self):
        repo = _mock_repo()
        request = _make_request({"authorization": "Bearer wrong-token"})
        with patch("cogos.api.auth.get_repo", return_value=repo):
            with pytest.raises(HTTPException) as exc_info:
                validate_token(request)
        assert exc_info.value.status_code == 401
        assert "Invalid" in exc_info.value.detail

    def test_bearer_prefix_required(self):
        request = _make_request({"authorization": "Basic abc123"})
        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)
        assert exc_info.value.status_code == 401
