"""Tests for cogos_api.auth — JWT creation, verification, expiry."""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt as pyjwt
import pytest

from cogos_api.auth import TokenClaims, create_session_token, verify_token

TEST_SECRET = "test-secret-key-for-unit-tests"


@pytest.fixture(autouse=True)
def _mock_signing_key():
    with patch("cogos_api.auth._get_signing_key", return_value=TEST_SECRET):
        # Reset cached key
        import cogos_api.auth

        cogos_api.auth._cached_signing_key = None
        yield
        cogos_api.auth._cached_signing_key = None


class TestCreateSessionToken:
    def test_returns_string(self):
        token = create_session_token("proc-123", "alpha")
        assert isinstance(token, str)

    def test_contains_expected_claims(self):
        token = create_session_token("proc-123", "alpha", ttl=600)
        payload = pyjwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["sub"] == "proc-123"
        assert payload["cogent"] == "alpha"
        assert "iat" in payload
        assert "exp" in payload

    def test_custom_ttl(self):
        now = time.time()
        token = create_session_token("proc-123", "alpha", ttl=120)
        payload = pyjwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["exp"] - payload["iat"] == 120


class TestVerifyToken:
    def test_valid_token(self):
        token = create_session_token("proc-123", "alpha")
        claims = verify_token(token)
        assert isinstance(claims, TokenClaims)
        assert claims.process_id == "proc-123"
        assert claims.cogent == "alpha"

    def test_expired_token(self):
        token = create_session_token("proc-123", "alpha", ttl=-1)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            verify_token(token)

    def test_invalid_signature(self):
        token = pyjwt.encode(
            {"sub": "proc-123", "cogent": "alpha", "iat": int(time.time()), "exp": int(time.time() + 600)},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(pyjwt.InvalidSignatureError):
            verify_token(token)

    def test_malformed_token(self):
        with pytest.raises(pyjwt.PyJWTError):
            verify_token("not-a-jwt")
