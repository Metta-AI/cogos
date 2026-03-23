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
        return f"cogent/{cogent_name}/{self.name}"

    def _fallback_keys(self) -> list[str]:
        """Additional secret keys to try if the primary key has no config."""
        return []

    def load_config(self, cogent_name: str, *, secrets_provider: object) -> dict[str, Any]:
        """Load persisted configuration from the secrets provider."""
        for key in [self._secret_key(cogent_name)] + self._fallback_keys():
            try:
                raw = secrets_provider.get_secret(key)  # type: ignore[union-attr]
                config = json.loads(raw)
                if config:
                    return config
            except (KeyError, json.JSONDecodeError):
                continue
            except Exception:
                logger.exception("Failed to load config from %s", key)
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

    def status(self, cogent_name: str, *, secrets_provider: object, _config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return current status: configured fields + readiness."""
        config = _config if _config is not None else self.load_config(cogent_name, secrets_provider=secrets_provider)
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


class NotificationsIntegration(Integration):
    @property
    def name(self) -> str:
        return "notifications"

    @property
    def display_name(self) -> str:
        return "Notifications"

    @property
    def description(self) -> str:
        return "Where to send alerts and approval requests."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="discord_handle", label="Discord Handle", required=False, placeholder="username", help_text="Your Discord username for DM notifications."),
            FieldSpec(name="discord_alerts", label="Alerts", field_type="toggle", required=False),
            FieldSpec(name="discord_requests", label="Requests", field_type="toggle", required=False),
            FieldSpec(name="email_address", label="Email Address", field_type="email", required=False, placeholder="you@example.com", help_text="Email address for notifications."),
            FieldSpec(name="email_alerts", label="Alerts", field_type="toggle", required=False),
            FieldSpec(name="email_requests", label="Requests", field_type="toggle", required=False),
        ]

    def status(self, cogent_name: str, *, secrets_provider: object, _config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = _config if _config is not None else self.load_config(cogent_name, secrets_provider=secrets_provider)
        has_discord = bool(config.get("discord_handle"))
        has_email = bool(config.get("email_address"))
        configured = has_discord or has_email
        return {"configured": configured, "missing_fields": []}


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
            FieldSpec(name="display_name", label="Display Name", required=False, help_text="Bot display name in Discord."),
            FieldSpec(name="default_channels", label="Default Channels", required=False, help_text="Comma-separated list of default channel names."),
        ]

    def status(self, cogent_name: str, *, secrets_provider: object, _config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check both shared bot token and per-cogent persona config."""
        # Check per-cogent persona config
        persona = _config if _config is not None else self.load_config(cogent_name, secrets_provider=secrets_provider)
        # Check shared bot token
        bot_configured = False
        try:
            raw = secrets_provider.get_secret("cogtainer/discord")  # type: ignore[union-attr]
            data = json.loads(raw)
            bot_configured = bool(data.get("access_token") or data.get("bot_token"))
        except Exception:
            pass
        has_persona = bool(persona.get("display_name"))
        configured = bot_configured and has_persona
        missing: list[str] = []
        if not bot_configured:
            missing.append("bot_token (shared)")
        if not has_persona:
            missing.append("display_name")
        return {"configured": configured, "missing_fields": missing}


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

    def _secret_key(self, cogent_name: str) -> str:
        return f"identity_service/{cogent_name}/{self.name}"


class AnthropicIntegration(Integration):
    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def display_name(self) -> str:
        return "Anthropic"

    @property
    def description(self) -> str:
        return "Anthropic API key for Claude model access."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="api_key", label="API Key", field_type="secret", help_text="Anthropic API key (sk-ant-...)."),
        ]

    def _fallback_keys(self) -> list[str]:
        return ["cogent/all/anthropic"]


class GeminiIntegration(Integration):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Gemini"

    @property
    def description(self) -> str:
        return "Google Gemini API key for model access."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="api_key", label="API Key", field_type="secret", help_text="Google AI API key for Gemini."),
        ]

    def _fallback_keys(self) -> list[str]:
        return ["cogent/all/gemini"]


# ── Registry ─────────────────────────────────────────────────────

INTEGRATIONS: list[Integration] = [
    NotificationsIntegration(),
    AnthropicIntegration(),
    GeminiIntegration(),
    EmailIntegration(),
    DiscordIntegration(),
    GitHubIntegration(),
    AsanaIntegration(),
]

INTEGRATIONS_BY_NAME: dict[str, Integration] = {i.name: i for i in INTEGRATIONS}
