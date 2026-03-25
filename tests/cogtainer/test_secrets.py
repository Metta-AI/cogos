"""Tests for SecretsProvider protocol and implementations."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cogtainer.secrets import (
    AwsSecretsProvider,
    LocalSecretsProvider,
    SecretsProvider,
    _extract_field,
    cogent_key,
    cogtainer_key,
    create_secrets_provider,
)

# ── _extract_field helper ────────────────────────────────────


def test_extract_field_none_returns_value():
    assert _extract_field("hello", None, "k") == "hello"


def test_extract_field_json_extracts():
    val = json.dumps({"user": "alice", "pass": "secret"})
    assert _extract_field(val, "user", "k") == "alice"


def test_extract_field_not_json_returns_none():
    assert _extract_field("plain-string", "field", "k") is None


def test_extract_field_missing_field_returns_none():
    val = json.dumps({"user": "alice"})
    assert _extract_field(val, "nonexistent", "k") is None


# ── LocalSecretsProvider ─────────────────────────────────────


@pytest.fixture()
def local_provider(tmp_path: Path) -> LocalSecretsProvider:
    return LocalSecretsProvider(data_dir=str(tmp_path))


def test_local_get_secret(tmp_path: Path, local_provider: LocalSecretsProvider):
    secrets_file = tmp_path / ".secrets.json"
    secrets_file.write_text(json.dumps({"my_key": "my_value"}))
    assert local_provider.get_secret("my_key") == "my_value"


def test_local_get_secret_with_field(tmp_path: Path, local_provider: LocalSecretsProvider):
    secrets_file = tmp_path / ".secrets.json"
    secrets_file.write_text(json.dumps({"creds": json.dumps({"user": "bob", "pass": "pw"})}))
    assert local_provider.get_secret("creds", field="user") == "bob"


def test_local_get_secret_missing_key(tmp_path: Path, local_provider: LocalSecretsProvider):
    secrets_file = tmp_path / ".secrets.json"
    secrets_file.write_text(json.dumps({"other": "val"}))
    with pytest.raises(KeyError):
        local_provider.get_secret("missing")


def test_local_get_secret_no_file(local_provider: LocalSecretsProvider):
    with pytest.raises(KeyError):
        local_provider.get_secret("anything")


def test_local_set_and_get(local_provider: LocalSecretsProvider):
    local_provider.set_secret("new_key", "new_value")
    assert local_provider.get_secret("new_key") == "new_value"


def test_local_set_preserves_existing(tmp_path: Path, local_provider: LocalSecretsProvider):
    local_provider.set_secret("a", "1")
    local_provider.set_secret("b", "2")
    assert local_provider.get_secret("a") == "1"
    assert local_provider.get_secret("b") == "2"


# ── Key helpers ──────────────────────────────────────────────


def test_cogtainer_key(monkeypatch):
    monkeypatch.setenv("COGTAINER", "agora")
    assert cogtainer_key("discord") == "cogtainer/agora/discord"


def test_cogtainer_key_raises_without_env():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="COGTAINER env var not set"):
            cogtainer_key("discord")


def test_cogent_key():
    assert cogent_key("alpha", "discord") == "cogent/alpha/discord"


# ── cogtainer_secret / cogent_secret on LocalSecretsProvider ─


def test_local_cogtainer_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COGTAINER", "agora")
    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    provider.set_secret("cogtainer/agora/discord", json.dumps({"bot_token": "tok"}))
    raw = provider.cogtainer_secret("discord")
    assert json.loads(raw)["bot_token"] == "tok"


def test_local_cogtainer_secret_with_field(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COGTAINER", "agora")
    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    provider.set_secret("cogtainer/agora/discord", json.dumps({"bot_token": "tok"}))
    assert provider.cogtainer_secret("discord", field="bot_token") == "tok"


def test_local_cogent_secret(tmp_path: Path):
    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    provider.set_secret("cogent/alpha/github", json.dumps({"app_id": "123"}))
    raw = provider.cogent_secret("alpha", "github")
    assert json.loads(raw)["app_id"] == "123"


# ── Factory ──────────────────────────────────────────────────


def test_factory_local(tmp_path: Path):
    provider = create_secrets_provider("local", data_dir=str(tmp_path))
    assert isinstance(provider, LocalSecretsProvider)


def test_factory_aws():
    session = MagicMock()
    provider = create_secrets_provider("aws", region="us-east-1", session=session)
    assert isinstance(provider, AwsSecretsProvider)


def test_factory_invalid():
    with pytest.raises(ValueError):
        create_secrets_provider("invalid")


# ── AwsSecretsProvider protocol conformance ──────────────────


def test_aws_provider_is_secrets_provider():
    session = MagicMock()
    provider = AwsSecretsProvider(region="us-east-1", session=session)
    assert isinstance(provider, SecretsProvider)
