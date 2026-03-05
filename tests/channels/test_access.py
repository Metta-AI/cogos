import os
from unittest.mock import MagicMock, patch

from channels.access import get_channel_token, get_channel_secret


class TestGetChannelToken:
    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "test-token-123"}):
            token = get_channel_token("discord")
            assert token == "test-token-123"

    def test_returns_none_when_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("channels.access._get_secrets_client") as mock_sm:
                mock_sm.return_value.get_secret_value.side_effect = Exception("not found")
                token = get_channel_token("discord")
                assert token is None


class TestGetChannelSecret:
    def test_returns_secret_dict(self):
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": '{"type": "static", "access_token": "abc"}'
        }
        with patch.dict(os.environ, {"COGENT_NAME": "test-cogent"}):
            with patch("channels.access._get_secrets_client", return_value=mock_sm):
                secret = get_channel_secret("discord")
                assert secret == {"type": "static", "access_token": "abc"}

    def test_returns_none_on_error(self):
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = Exception("boom")
        with patch("channels.access._get_secrets_client", return_value=mock_sm):
            secret = get_channel_secret("discord")
            assert secret is None
