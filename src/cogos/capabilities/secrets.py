"""Secrets capability — retrieve secrets from key manager."""

from __future__ import annotations

import fnmatch
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

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        key = "keys"
        old = existing.get(key)
        new = requested.get(key)
        if old is not None and new is not None:
            result[key] = [p for p in old if p in new]
        elif old is not None:
            result[key] = old
        elif new is not None:
            result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        patterns = self._scope.get("keys")
        if patterns is None:
            return
        key = context.get("key", "")
        for pattern in patterns:
            if fnmatch.fnmatch(str(key), pattern):
                return
        raise PermissionError(
            f"Secret key '{key}' not permitted; allowed patterns: {patterns}"
        )

    def get(self, key: str) -> SecretValue | SecretError:
        self._check("get", key=key)
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
