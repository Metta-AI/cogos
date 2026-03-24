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

from cogtainer.secrets import cogtainer_key

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

    def cogtainer_fields(self) -> list[FieldSpec]:
        """Return cogtainer-level secret fields prompted during cogtainer create.

        Each field's ``name`` is used as the sub-key under
        ``cogtainer/{cogtainer_name}/{integration_name}/``.
        Override in subclasses that need shared cogtainer-level config.
        """
        return []

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

    def cogtainer_fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="bot_token", label="Discord Bot Token", field_type="secret", required=False, help_text="Shared bot token for all cogents in this cogtainer."),
        ]

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
            raw = secrets_provider.cogtainer_secret("discord")  # type: ignore[union-attr]
            data = json.loads(raw)
            bot_configured = bool(data.get("access_token") or data.get("bot_token"))
        except Exception as exc:
            logger.warning("Discord bot token check failed: %s: %s", type(exc).__name__, exc)
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

    def _fallback_keys(self) -> list[str]:
        return ["cogent/all/github"]

    def cogtainer_fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="org", label="GitHub Organization", required=False, help_text="GitHub org name (e.g. Metta-AI)."),
        ]

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="access_token", label="Personal Access Token", field_type="secret", required=False, help_text="GitHub PAT (ghp_...). Use this OR App credentials below."),
            FieldSpec(name="app_id", label="App ID", required=False, help_text="GitHub App ID (alternative to PAT)."),
            FieldSpec(name="private_key", label="Private Key", field_type="secret", required=False, help_text="PEM-encoded private key for the GitHub App."),
            FieldSpec(name="webhook_secret", label="Webhook Secret", field_type="secret", required=False, help_text="Shared secret for webhook signature verification."),
            FieldSpec(name="installation_id", label="Installation ID", required=False, help_text="Installation ID if pre-configured."),
        ]

    def status(self, cogent_name: str, *, secrets_provider: object, _config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = _config if _config is not None else self.load_config(cogent_name, secrets_provider=secrets_provider)
        has_pat = bool(config.get("access_token"))
        has_app = bool(config.get("app_id") and config.get("private_key"))
        configured = has_pat or has_app
        missing: list[str] = []
        if not configured:
            missing.append("access_token or app_id+private_key")
        return {"configured": configured, "missing_fields": missing}


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

    def cogtainer_fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="domain", label="Asana Workspace Domain", required=False, help_text="Asana workspace domain (e.g. softmax)."),
        ]

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

    def cogtainer_fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="domain", label="Email Domain", required=False, help_text="Domain for cogent emails (e.g. example-cogents.com)."),
        ]

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="address", label="Email Address", field_type="email", required=False, help_text="Auto-configured as cogent-name@<your-domain>."),
            FieldSpec(name="ses_region", label="SES Region", required=False, placeholder="us-east-1", help_text="AWS region for SES."),
            FieldSpec(name="ingest_url", label="Ingest URL", field_type="url", required=False, help_text="CloudFlare worker URL for inbound mail."),
        ]

    @staticmethod
    def address_for(cogent_name: str, domain: str = "") -> str:
        """Derive the email address for a cogent."""
        if not domain:
            return ""
        return f"{cogent_name}@{domain}"

    def _secret_key(self, cogent_name: str) -> str:
        return f"cogent/{cogent_name}/{self.name}"

    def status(self, cogent_name: str, *, secrets_provider: object, _config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Email is configured when the cogtainer email domain secret is set."""
        domain = self._read_domain(secrets_provider)
        address = self.address_for(cogent_name, domain)
        return {"configured": bool(address), "missing_fields": [] if address else ["domain"], "address": address}

    @staticmethod
    def _read_domain(secrets_provider: object) -> str:
        """Read email domain from cogtainer/{name}/email/domain secret."""
        cogtainer = os.environ.get("COGTAINER", "")
        if cogtainer and hasattr(secrets_provider, "get_secret"):
            try:
                return secrets_provider.get_secret(f"cogtainer/{cogtainer}/email/domain")  # type: ignore[union-attr]
            except Exception:
                pass
        return ""


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
        try:
            return [cogtainer_key("anthropic")]
        except RuntimeError:
            return []


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
        try:
            return [cogtainer_key("gemini")]
        except RuntimeError:
            return []


class WebIntegration(Integration):
    @property
    def name(self) -> str:
        return "web"

    @property
    def display_name(self) -> str:
        return "Web"

    @property
    def description(self) -> str:
        return "Web publishing and static file hosting."

    def cogtainer_fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="domain", label="Web Domain", required=False, help_text="Domain for cogent dashboards (e.g. example-cogents.com)."),
        ]

    def fields(self) -> list[FieldSpec]:
        return []

    def status(self, cogent_name: str, *, secrets_provider: object, _config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"configured": True, "missing_fields": []}


class GoogleIntegration(Integration):
    """Provide Google Drive, Docs, Sheets, and Calendar access via a per-cogent
    GCP service account whose JSON key is stored in Secrets Manager."""

    @property
    def name(self) -> str:
        return "google"

    @property
    def display_name(self) -> str:
        return "Google"

    @property
    def description(self) -> str:
        return "Access Google Drive, Docs, Sheets, and Calendar via service account."

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec(name="share_email", label="Share With", field_type="text", required=False, help_text="Share files/calendars with this email (read-only)."),
            FieldSpec(name="drive_enabled", label="Google Drive", field_type="toggle", required=False, help_text="Enable access to Google Drive."),
            FieldSpec(name="docs_enabled", label="Google Docs", field_type="toggle", required=False, help_text="Enable access to Google Docs."),
            FieldSpec(name="sheets_enabled", label="Google Sheets", field_type="toggle", required=False, help_text="Enable access to Google Sheets."),
            FieldSpec(name="calendar_enabled", label="Google Calendar", field_type="toggle", required=False, help_text="Enable access to Google Calendar."),
        ]

    def status(
        self,
        cogent_name: str,
        *,
        secrets_provider: object,
        _config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check whether the service account key has been provisioned."""
        config = (
            _config
            if _config is not None
            else self.load_config(cogent_name, secrets_provider=secrets_provider)
        )
        has_key = bool(config.get("private_key") or config.get("type") == "service_account")
        group_email = config.get("group_email", "")
        sa_email = config.get("service_account_email", "")
        return {
            "configured": has_key,
            "missing_fields": [] if has_key else ["service_account_key"],
            "share_email": group_email or sa_email,
        }


# ── Registry ─────────────────────────────────────────────────────

INTEGRATIONS: list[Integration] = [
    NotificationsIntegration(),
    AnthropicIntegration(),
    GeminiIntegration(),
    EmailIntegration(),
    WebIntegration(),
    DiscordIntegration(),
    GitHubIntegration(),
    AsanaIntegration(),
    GoogleIntegration(),
]

INTEGRATIONS_BY_NAME: dict[str, Integration] = {i.name: i for i in INTEGRATIONS}
