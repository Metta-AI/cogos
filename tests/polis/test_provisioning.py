from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import requests

from polis.provisioning import (
    destroy_asana_guest,
    destroy_discord_role,
    destroy_ses_email,
    provision_asana_guest,
    provision_discord_role,
    provision_github_credentials,
    provision_ses_email,
)
from polis.secrets.store import SecretStore


class FakeSesClient:
    def __init__(self, *, already_exists=False):
        self.created = []
        self._already_exists = already_exists

    def get_email_identity(self, EmailIdentity):
        if self._already_exists:
            return {"VerificationStatus": "SUCCESS"}
        raise self._not_found()

    def create_email_identity(self, EmailIdentity, Tags=None):
        self.created.append(EmailIdentity)
        return {"IdentityType": "EMAIL_ADDRESS"}

    def _not_found(self):
        error = MagicMock()
        error.response = {"Error": {"Code": "NotFoundException"}}
        exc = type("NotFoundException", (Exception,), {"response": error.response})
        return exc("not found")


class FakeStore:
    def __init__(self) -> None:
        self.secrets: dict[str, dict[str, Any]] = {}

    def put(self, path: str, value: dict[str, Any]) -> None:
        self.secrets[path] = value

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        if path in self.secrets:
            return self.secrets[path]
        raise Exception("not found")

    def as_store(self) -> SecretStore:
        return cast(SecretStore, self)


# --- SES ---


def test_provision_ses_email_creates_identity():
    ses = FakeSesClient()
    store = FakeStore()
    result = provision_ses_email(
        ses_client=ses, store=store.as_store(), cogent_name="scout", domain="softmax-cogents.com"
    )
    assert result["email"] == "scout@softmax-cogents.com"
    assert ses.created == ["scout@softmax-cogents.com"]
    assert "cogent/scout/ses_identity" in store.secrets


def test_provision_ses_email_idempotent():
    ses = FakeSesClient(already_exists=True)
    store = FakeStore()
    result = provision_ses_email(
        ses_client=ses, store=store.as_store(), cogent_name="scout", domain="softmax-cogents.com"
    )
    assert result["email"] == "scout@softmax-cogents.com"
    assert ses.created == []


# --- Discord ---


def test_provision_discord_role_creates_role(monkeypatch):
    store = FakeStore()
    store.secrets["polis/discord"] = {
        "bot_token": "fake-token",
        "guild_id": "111222333",
    }

    get_resp = MagicMock()
    get_resp.json.return_value = []
    get_resp.raise_for_status = MagicMock()

    post_resp = MagicMock()
    post_resp.json.return_value = {"id": "999888777", "name": "cogent-scout"}
    post_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(requests, "get", lambda url, **kw: get_resp)
    monkeypatch.setattr(requests, "post", lambda url, **kw: post_resp)

    result = provision_discord_role(store=store.as_store(), cogent_name="scout")
    assert result["role_id"] == "999888777"
    assert result["role_name"] == "cogent-scout"
    assert result["created"] is True
    assert store.secrets["cogent/scout/discord_role_id"]["role_id"] == "999888777"


def test_provision_discord_role_idempotent(monkeypatch):
    store = FakeStore()
    store.secrets["polis/discord"] = {
        "bot_token": "fake-token",
        "guild_id": "111222333",
    }

    get_resp = MagicMock()
    get_resp.json.return_value = [
        {"id": "999888777", "name": "cogent-scout"},
        {"id": "123", "name": "other-role"},
    ]
    get_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(requests, "get", lambda url, **kw: get_resp)

    result = provision_discord_role(store=store.as_store(), cogent_name="scout")
    assert result["role_id"] == "999888777"
    assert result["created"] is False


# --- Asana ---


def test_provision_asana_guest_invites_user(monkeypatch):
    store = FakeStore()
    store.secrets["polis/asana"] = {
        "access_token": "fake-asana-pat",
        "workspace_gid": "ws-123",
    }

    post_resp = MagicMock()
    post_resp.json.return_value = {
        "data": {"gid": "asana-user-456", "name": "scout"}
    }
    post_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(requests, "post", lambda url, **kw: post_resp)

    result = provision_asana_guest(
        store=store.as_store(), cogent_name="scout", domain="softmax-cogents.com"
    )
    assert result["user_gid"] == "asana-user-456"
    assert result["status"] == "invited"
    assert store.secrets["cogent/scout/asana_user_gid"]["user_gid"] == "asana-user-456"


# --- GitHub ---


def test_provision_github_credentials_copies_shared_app():
    store = FakeStore()
    store.secrets["polis/github_app"] = {
        "type": "github_app",
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }
    result = provision_github_credentials(store=store.as_store(), cogent_name="scout")
    assert result["type"] == "github_app"
    assert result["created"] is True
    assert store.secrets["cogent/scout/github"]["app_id"] == "12345"


def test_provision_github_credentials_idempotent():
    store = FakeStore()
    store.secrets["polis/github_app"] = {
        "type": "github_app",
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }
    store.secrets["cogent/scout/github"] = {
        "type": "github_app",
        "app_id": "12345",
        "private_key": "fake-key",
        "installation_id": "67890",
    }
    result = provision_github_credentials(store=store.as_store(), cogent_name="scout")
    assert result["created"] is False


# --- Destroy ---


def test_destroy_discord_role(monkeypatch):
    store = FakeStore()
    store.secrets["polis/discord"] = {"bot_token": "fake-token", "guild_id": "111"}
    store.secrets["cogent/scout/discord_role_id"] = {
        "role_id": "999",
        "role_name": "cogent-scout",
        "guild_id": "111",
    }

    deleted = []
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(
        requests, "delete", lambda url, **kw: (deleted.append(url), mock_resp)[1]
    )

    destroy_discord_role(store=store.as_store(), cogent_name="scout")
    assert any("roles/999" in u for u in deleted)


def test_destroy_ses_email():
    ses = MagicMock()
    destroy_ses_email(ses_client=ses, cogent_name="scout", domain="softmax-cogents.com")
    ses.delete_email_identity.assert_called_once_with(
        EmailIdentity="scout@softmax-cogents.com"
    )


def test_destroy_asana_guest(monkeypatch):
    store = FakeStore()
    store.secrets["polis/asana"] = {
        "access_token": "fake-pat",
        "workspace_gid": "ws-123",
    }
    store.secrets["cogent/scout/asana_user_gid"] = {
        "user_gid": "asana-456",
        "workspace_gid": "ws-123",
    }

    posted = []
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: (posted.append(url), mock_resp)[1]
    )

    destroy_asana_guest(store=store.as_store(), cogent_name="scout")
    assert any("removeUser" in u for u in posted)
