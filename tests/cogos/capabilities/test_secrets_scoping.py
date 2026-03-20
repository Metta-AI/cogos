"""Tests for SecretsCapability scoping: _narrow(), _check(), get() guards."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.secrets import SecretError, SecretsCapability


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


def _mock_provider(value="secret123"):
    provider = MagicMock()
    provider.get_secret.return_value = value
    return provider


class TestUnscopedGet:
    def test_unscoped_allows_any_key(self, repo, pid):
        provider = _mock_provider()
        cap = SecretsCapability(repo, pid, secrets_provider=provider)
        result = cap.get("any-key")
        assert result.key == "any-key"
        assert not isinstance(result, SecretError)
        assert result.value == "secret123"


class TestScopedGet:
    def test_scoped_keys_allows_matching(self, repo, pid):
        provider = _mock_provider("val")
        cap = SecretsCapability(repo, pid, secrets_provider=provider).scope(keys=["app/*"])
        result = cap.get("app/db-password")
        assert not isinstance(result, SecretError)
        assert result.value == "val"

    def test_scoped_keys_denies_non_matching(self, repo, pid):
        provider = _mock_provider()
        cap = SecretsCapability(repo, pid, secrets_provider=provider).scope(keys=["app/*"])
        with pytest.raises(PermissionError):
            cap.get("other/secret")

    def test_scoped_keys_exact_match(self, repo, pid):
        provider = _mock_provider("val")
        cap = SecretsCapability(repo, pid, secrets_provider=provider).scope(keys=["my-api-key"])
        result = cap.get("my-api-key")
        assert not isinstance(result, SecretError)
        assert result.value == "val"

    def test_scoped_keys_multiple_patterns(self, repo, pid):
        provider = _mock_provider("v")
        cap = SecretsCapability(repo, pid, secrets_provider=provider).scope(keys=["app/*", "db/*"])
        cap.get("app/key")
        cap.get("db/password")
        with pytest.raises(PermissionError):
            cap.get("other/key")


class TestNarrow:
    def test_narrow_intersects_key_patterns(self, repo, pid):
        cap = SecretsCapability(repo, pid)
        s1 = cap.scope(keys=["app/*", "db/*"])
        s2 = s1.scope(keys=["app/*", "cache/*"])
        assert set(s2._scope["keys"]) == {"app/*"}

    def test_narrow_only_existing_keeps_existing(self, repo, pid):
        cap = SecretsCapability(repo, pid)
        s1 = cap.scope(keys=["app/*"])
        # Narrow with no keys — existing stays
        s2 = s1.scope()
        assert s2._scope["keys"] == ["app/*"]

    def test_narrow_only_requested_keeps_requested(self, repo, pid):
        cap = SecretsCapability(repo, pid)
        s1 = cap.scope(keys=["app/*"])
        assert s1._scope["keys"] == ["app/*"]
