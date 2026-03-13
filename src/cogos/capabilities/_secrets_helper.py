"""Shared secret fetching — SSM Parameter Store with Secrets Manager fallback."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def fetch_secret(key: str, field: str | None = None) -> str:
    """Fetch a secret value from AWS SSM Parameter Store or Secrets Manager.

    If `key` contains ``{cogent}``, it is replaced with the ``COGENT_NAME``
    environment variable (e.g., ``cogent/{cogent}/github`` becomes
    ``cogent/dr.alpha/github``).

    If `field` is specified and the secret value is JSON, returns that field.

    Tries SSM first, then Secrets Manager. Returns the string value.
    Raises RuntimeError if both fail.
    """
    import boto3

    # Resolve {cogent} placeholder
    if "{cogent}" in key:
        cogent_name = os.environ.get("COGENT_NAME", "")
        if not cogent_name:
            raise RuntimeError(
                f"Secret key '{key}' contains {{cogent}} but COGENT_NAME env var is not set"
            )
        key = key.replace("{cogent}", cogent_name)

    # Try SSM Parameter Store
    try:
        client = boto3.client("ssm")
        resp = client.get_parameter(Name=key, WithDecryption=True)
        value = resp["Parameter"]["Value"]
        return _extract_field(value, field, key)
    except Exception:
        pass

    # Try Secrets Manager
    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=key)
        value = resp.get("SecretString")
        if value is None:
            raise RuntimeError(f"Secret '{key}' is binary, not string")
        return _extract_field(value, field, key)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not fetch secret '{key}': {exc}") from exc


def _extract_field(value: str, field: str | None, key: str) -> str:
    """Extract a field from a JSON secret value, or return raw value."""
    if field is None:
        return value
    try:
        parsed = json.loads(value)
        if field in parsed:
            return parsed[field]
        raise RuntimeError(f"Secret '{key}' does not contain field '{field}'")
    except json.JSONDecodeError:
        raise RuntimeError(f"Secret '{key}' is not JSON but field '{field}' was requested")
