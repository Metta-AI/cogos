import json
import os
from unittest.mock import MagicMock, patch

from cogos.io.access import get_io_token, get_io_secret


def _mock_provider(secrets=None):
    """Create a mock SecretsProvider."""
    provider = MagicMock()
    if secrets:
        def _get(key, field=None):
            if key not in secrets:
                raise KeyError(key)
            val = secrets[key]
            if field:
                parsed = json.loads(val)
                return parsed.get(field, val)
            return val
        provider.get_secret.side_effect = _get

        def _cogent_secret(cogent_name, key, field=None):
            return _get(f"cogent/{cogent_name}/{key}", field=field)
        provider.cogent_secret.side_effect = _cogent_secret
    else:
        provider.get_secret.side_effect = KeyError("not found")
        provider.cogent_secret.side_effect = KeyError("not found")
    return provider


class TestGetChannelToken:
    def test_env_var_fallback(self):
        provider = _mock_provider()
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "test-token-123"}):
            token = get_io_token("discord", secrets_provider=provider)
            assert token == "test-token-123"

    def test_returns_none_when_unavailable(self):
        provider = _mock_provider()
        with patch.dict(os.environ, {}, clear=True):
            token = get_io_token("discord", secrets_provider=provider)
            assert token is None


class TestGetChannelSecret:
    def test_returns_secret_dict(self):
        provider = _mock_provider({
            "cogent/test-cogent/discord": '{"type": "static", "access_token": "abc"}'
        })
        with patch.dict(os.environ, {"COGENT": "test-cogent"}):
            secret = get_io_secret("discord", secrets_provider=provider)
            assert secret == {"type": "static", "access_token": "abc"}

    def test_returns_none_on_error(self):
        provider = _mock_provider()
        secret = get_io_secret("discord", secrets_provider=provider)
        assert secret is None
