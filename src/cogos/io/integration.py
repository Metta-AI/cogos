"""Integration base class and concrete integrations.

Each integration defines its configuration fields and uses the SecretsProvider
for storage under ``identity_service/{cogent_name}/{channel}``.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class FieldSpec:
    """Describes a single configuration field for an integration."""

    name: str
    label: str
    field_type: str = "text"  # text | secret | url | email | textarea
    required: bool = True
    help_text: str = ""
    placeholder: str = ""


class Integration(ABC):
    """Base class for IO integrations.

    Subclasses declare their config fields and the secret key used for storage.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Machine-readable integration name (e.g. 'discord')."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable label shown in the dashboard."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of the integration."""
        ...

    @abstractmethod
    def fields(self) -> list[FieldSpec]:
        """Return the list of configurable fields."""
        ...

    # ── secrets storage ──────────────────────────────────────────

    def _secret_key(self, cogent_name: str) -> str:
        return f"identity_service/{cogent_name}/{self.name}"

    def load_config(self, cogent_name: str, *, secrets_provider: object) -> dict[str, Any]:
        """Load persisted configuration from the secrets provider."""
        key = self._secret_key(cogent_name)
        try:
            raw = secrets_provider.get_secret(key)  # type: ignore[union-attr]
            return json.loads(raw)
        except (KeyError, json.JSONDecodeError):
            return {}

    def save_config(self, cogent_name: str, config: dict[str, Any], *, secrets_provider: object) -> None:
        """Persist configuration via the secrets provider."""
        key = self._secret_key(cogent_name)
        # Preserve existing fields not included in this update
        existing = self.load_config(cogent_name, secrets_provider=secrets_provider)
        merged = {**existing, **config, "type": self.name}
        secrets_provider.set_secret(key, json.dumps(merged))  # type: ignore[union-attr]

    def delete_config(self, cogent_name: str, *, secrets_provider: object) -> None:
        """Remove stored configuration."""
        key = self._secret_key(cogent_name)
        secrets_provider.delete_secret(key)  # type: ignore[union-attr]

    def status(self, cogent_name: str, *, secrets_provider: object) -> dict[str, Any]:
        """Return current status: configured fields + readiness."""
        config = self.load_config(cogent_name, secrets_provider=secrets_provider)
        configured = bool(config)
        required_fields = [f.name for f in self.fields() if f.required]
        missing = [f for f in required_fields if not config.get(f)]
        return {
            "configured": configured and len(missing) == 0,
            "missing_fields": missing,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialise the integration definition (no secret values)."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.field_type,
                    "required": f.required,
                    "help_text": f.help_text,
                    "placeholder": f.placeholder,
                }
                for f in self.fields()
            ],
        }


# ── Concrete integrations ────────────────────────────────────────


class DiscordIntegration(Integration):
    @property
    def name(self) -> str:
        return "discord"

    @property
    def display_name(self) -> str:
        return "Discord"

    @property
    def description(self) -> str:
        return "Connect to Discord to receive and send messages via a bot."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="bot_token", label="Bot Token", field_type="secret", help_text="Discord bot token from the Developer Portal."),
            FieldSpec(name="application_id", label="Application ID", help_text="Discord application ID."),
            FieldSpec(name="guild_id", label="Guild ID", required=False, help_text="Restrict the bot to a specific server."),
        ]


class GitHubIntegration(Integration):
    @property
    def name(self) -> str:
        return "github"

    @property
    def display_name(self) -> str:
        return "GitHub"

    @property
    def description(self) -> str:
        return "Connect to GitHub to receive webhooks and interact with repositories."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="app_id", label="App ID", help_text="GitHub App ID."),
            FieldSpec(name="private_key", label="Private Key", field_type="secret", help_text="PEM-encoded private key for the GitHub App.", placeholder="-----BEGIN RSA PRIVATE KEY-----"),
            FieldSpec(name="webhook_secret", label="Webhook Secret", field_type="secret", required=False, help_text="Shared secret for webhook signature verification."),
            FieldSpec(name="installation_id", label="Installation ID", required=False, help_text="Installation ID if pre-configured."),
        ]


class AsanaIntegration(Integration):
    @property
    def name(self) -> str:
        return "asana"

    @property
    def display_name(self) -> str:
        return "Asana"

    @property
    def description(self) -> str:
        return "Connect to Asana to sync tasks and receive project updates."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="access_token", label="Personal Access Token", field_type="secret", help_text="Asana personal access token."),
            FieldSpec(name="workspace_id", label="Workspace ID", required=False, help_text="Asana workspace GID."),
            FieldSpec(name="project_id", label="Project ID", required=False, help_text="Default project GID for task operations."),
        ]


class EmailIntegration(Integration):
    @property
    def name(self) -> str:
        return "email"

    @property
    def display_name(self) -> str:
        return "Email"

    @property
    def description(self) -> str:
        return "Send and receive email via CloudFlare + SES."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="address", label="Email Address", field_type="email", help_text="The email address assigned to this cogent."),
            FieldSpec(name="ses_region", label="SES Region", required=False, placeholder="us-east-1", help_text="AWS region for SES."),
            FieldSpec(name="ingest_url", label="Ingest URL", field_type="url", required=False, help_text="CloudFlare worker URL for inbound mail."),
        ]


# ── Registry ─────────────────────────────────────────────────────

INTEGRATIONS: list[Integration] = [
    DiscordIntegration(),
    GitHubIntegration(),
    AsanaIntegration(),
    EmailIntegration(),
]

INTEGRATIONS_BY_NAME: dict[str, Integration] = {i.name: i for i in INTEGRATIONS}
