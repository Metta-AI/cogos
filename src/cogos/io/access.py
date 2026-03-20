"""IO token access: fetches tokens from the secrets provider."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from cogos.capabilities._secrets_helper import fetch_secret

logger = logging.getLogger(__name__)


def get_io_token(channel: str, *, secrets_provider: object) -> str | None:
    """Get a channel's access token.

    Checks env var <CHANNEL>_BOT_TOKEN first, then the secrets provider.
    """
    env_key = f"{channel.upper()}_BOT_TOKEN"
    env_token = os.environ.get(env_key)
    if env_token:
        logger.info("Using %s from environment", env_key)
        return env_token

    cogent_name = os.environ.get("COGENT_NAME")
    if not cogent_name:
        logger.error("COGENT_NAME not set in environment")
        return None

    try:
        secret_id = f"identity_service/{cogent_name}/{channel}"
        raw = fetch_secret(secret_id, field="access_token", secrets_provider=secrets_provider)
        return raw
    except Exception:
        logger.exception("Failed to fetch %s token from secrets provider", channel)
        return None


def get_io_secret(channel: str, *, secrets_provider: object) -> dict[str, Any] | None:
    """Get the full secret dict for a channel."""
    cogent_name = os.environ.get("COGENT_NAME")
    if not cogent_name:
        logger.error("COGENT_NAME not set in environment")
        return None

    try:
        secret_id = f"identity_service/{cogent_name}/{channel}"
        raw = fetch_secret(secret_id, secrets_provider=secrets_provider)
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to fetch %s secret from secrets provider", channel)
        return None
