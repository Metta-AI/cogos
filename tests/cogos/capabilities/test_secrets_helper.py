"""Tests for _secrets_helper.fetch_secret."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogos.capabilities._secrets_helper import fetch_secret


def _mock_provider(secrets=None, raise_on=None):
    """Create a mock SecretsProvider.

    secrets: dict mapping key -> value (or key -> {field: value} for JSON)
    raise_on: set of keys that should raise KeyError
    """
    provider = MagicMock()

    def _get(key, field=None):
        if raise_on and key in raise_on:
            raise KeyError(key)
        if secrets and key in secrets:
            return secrets[key] if field is None else secrets[key]
        raise KeyError(key)

    provider.get_secret.side_effect = _get
    return provider


class TestFetchSecretBasic:
    def test_returns_value(self):
        provider = MagicMock()
        provider.get_secret.return_value = "my-secret-value"
        result = fetch_secret("cogos/api-key", secrets_provider=provider)
        assert result == "my-secret-value"
        provider.get_secret.assert_called_with("cogos/api-key", field=None)

    def test_passes_field(self):
        provider = MagicMock()
        provider.get_secret.return_value = "tok123"
        result = fetch_secret("my/secret", field="access_token", secrets_provider=provider)
        assert result == "tok123"
        provider.get_secret.assert_called_with("my/secret", field="access_token")

    def test_raises_on_not_found(self):
        provider = MagicMock()
        provider.get_secret.side_effect = KeyError("not found")
        with pytest.raises(RuntimeError, match="Could not fetch secret"):
            fetch_secret("cogos/api-key", secrets_provider=provider)


class TestCogentPlaceholder:
    @patch.dict("os.environ", {"COGENT": "dr.alpha"})
    def test_resolves_cogent_placeholder(self):
        provider = MagicMock()
        provider.get_secret.return_value = "val"
        result = fetch_secret("cogent/{cogent}/github", secrets_provider=provider)
        assert result == "val"
        provider.get_secret.assert_called_with("cogent/dr.alpha/github", field=None)

    def test_raises_without_cogent_name(self):
        provider = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="COGENT env var is not set"):
                fetch_secret("cogent/{cogent}/github", secrets_provider=provider)


class TestAllFallback:
    @patch.dict("os.environ", {"COGENT": "agora"})
    def test_falls_back_to_all(self):
        """When cogent-specific secret missing, falls back to cogent/all/..."""
        provider = _mock_provider(
            secrets={"cogent/all/gemini": "shared-key"},
            raise_on={"cogent/agora/gemini"},
        )
        result = fetch_secret("cogent/{cogent}/gemini", secrets_provider=provider)
        assert result == "shared-key"

    @patch.dict("os.environ", {"COGENT": "agora"})
    def test_cogent_specific_takes_precedence(self):
        """Cogent-specific secret is preferred over cogent/all."""
        provider = _mock_provider(
            secrets={
                "cogent/agora/gemini": "agora-key",
                "cogent/all/gemini": "shared-key",
            },
        )
        result = fetch_secret("cogent/{cogent}/gemini", secrets_provider=provider)
        assert result == "agora-key"

    @patch.dict("os.environ", {"COGENT": "agora"})
    def test_raises_when_both_missing(self):
        """Raises RuntimeError when neither cogent-specific nor all exists."""
        provider = _mock_provider(
            raise_on={"cogent/agora/gemini", "cogent/all/gemini"},
        )
        with pytest.raises(RuntimeError, match="Could not fetch secret"):
            fetch_secret("cogent/{cogent}/gemini", secrets_provider=provider)

    def test_no_fallback_for_non_cogent_keys(self):
        """Keys without {cogent} placeholder don't get an all fallback."""
        provider = MagicMock()
        provider.get_secret.side_effect = KeyError("nope")
        with pytest.raises(RuntimeError, match="Could not fetch secret"):
            fetch_secret("some/other/key", secrets_provider=provider)
        provider.get_secret.assert_called_once_with("some/other/key", field=None)
