"""Secrets capability — retrieve secrets from key manager."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get(*, key: str, repo: Any, process_id: str | None = None, **kw: Any) -> dict:
    """Retrieve a secret value by key from the key manager.

    The key should reference a key manager key (e.g. AWS Secrets Manager ARN,
    SSM Parameter Store path, or a logical secret name mapped in capability config).
    """
    cap_config = kw.get("cap_config") or {}
    key_manager = cap_config.get("key_manager", "ssm")

    # Look up the secret via the configured key manager
    import boto3

    if key_manager == "secretsmanager":
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=key)
        value = resp.get("SecretString")
        if value is None:
            return {"key": key, "error": "Secret is binary, not string"}
        try:
            parsed = json.loads(value)
            return {"key": key, "value": parsed}
        except json.JSONDecodeError:
            return {"key": key, "value": value}
    else:
        # Default: SSM Parameter Store
        client = boto3.client("ssm")
        resp = client.get_parameter(Name=key, WithDecryption=True)
        value = resp["Parameter"]["Value"]
        return {"key": key, "value": value}
