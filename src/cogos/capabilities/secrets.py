"""Secrets capability — retrieve secrets from key manager."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class SecretValue(BaseModel):
    key: str
    value: Any = None


class SecretError(BaseModel):
    key: str
    error: str


# ── Capability ───────────────────────────────────────────────


class SecretsCapability(Capability):
    """Secret retrieval from AWS SSM or Secrets Manager.

    Usage:
        secrets.get("my-api-key")
    """

    def get(self, key: str) -> SecretValue | SecretError:
        import boto3

        try:
            # Try SSM Parameter Store first
            client = boto3.client("ssm")
            resp = client.get_parameter(Name=key, WithDecryption=True)
            value = resp["Parameter"]["Value"]
            return SecretValue(key=key, value=value)
        except Exception:
            pass

        try:
            client = boto3.client("secretsmanager")
            resp = client.get_secret_value(SecretId=key)
            value = resp.get("SecretString")
            if value is None:
                return SecretError(key=key, error="Secret is binary, not string")
            try:
                parsed = json.loads(value)
                return SecretValue(key=key, value=parsed)
            except json.JSONDecodeError:
                return SecretValue(key=key, value=value)
        except Exception as exc:
            return SecretError(key=key, error=str(exc))

    def __repr__(self) -> str:
        return "<SecretsCapability get()>"
