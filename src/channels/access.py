"""Channel token access: fetches tokens from AWS Secrets Manager with env var fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)


def _get_secrets_client(region: str | None = None):
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("secretsmanager", region_name=region)


def get_channel_token(cogent_id: str, channel: str) -> str | None:
    """Get a channel's access token.

    Checks env var <CHANNEL>_BOT_TOKEN first, then Secrets Manager.
    """
    env_key = f"{channel.upper()}_BOT_TOKEN"
    env_token = os.environ.get(env_key)
    if env_token:
        logger.info("Using %s from environment", env_key)
        return env_token

    try:
        sm = _get_secrets_client()
        secret_id = f"identity_service/{cogent_id}/{channel}"
        resp = sm.get_secret_value(SecretId=secret_id)
        data = json.loads(resp["SecretString"])
        return data.get("access_token")
    except Exception:
        logger.exception("Failed to fetch %s token from Secrets Manager", channel)
        return None


def get_channel_secret(cogent_id: str, channel: str) -> dict[str, Any] | None:
    """Get the full secret dict for a channel."""
    try:
        sm = _get_secrets_client()
        secret_id = f"identity_service/{cogent_id}/{channel}"
        resp = sm.get_secret_value(SecretId=secret_id)
        return json.loads(resp["SecretString"])
    except Exception:
        logger.exception("Failed to fetch %s secret from Secrets Manager", channel)
        return None
