"""SecretsProvider protocol and implementations.

Abstracts secret retrieval so that capabilities and runtimes don't
depend directly on AWS SDK calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ── Helper ───────────────────────────────────────────────────


def _extract_field(value: str, field: str | None, key: str) -> str | None:
    """Extract *field* from a JSON-encoded *value*.

    If *field* is ``None``, returns *value* unchanged.
    If *value* is not valid JSON or the field is missing, returns ``None``.
    """
    if field is None:
        return value
    try:
        parsed = json.loads(value)
        return parsed.get(field)
    except (json.JSONDecodeError, TypeError):
        return None


# ── Protocol ─────────────────────────────────────────────────


@runtime_checkable
class SecretsProvider(Protocol):
    """Minimal interface for reading/writing secrets."""

    def get_secret(self, key: str, field: str | None = None) -> str:
        """Return the secret value for *key*.

        If *field* is set and the value is JSON, extract that field.
        Raises ``KeyError`` when the secret is not found.
        """
        ...

    def set_secret(self, key: str, value: str) -> None:
        """Persist *value* under *key*."""
        ...

    def list_secrets(self, prefix: str) -> list[str]:
        """Return secret keys matching *prefix*."""
        ...

    def delete_secret(self, key: str) -> None:
        """Delete the secret identified by *key*."""
        ...

    def cogtainer_secret(self, key: str, field: str | None = None) -> str:
        """Read ``cogtainer/{COGTAINER}/{key}``."""
        ...

    def cogent_secret(self, cogent_name: str, key: str, field: str | None = None) -> str:
        """Read ``cogent/{cogent_name}/{key}``."""
        ...


# ── Key helpers ─────────────────────────────────────────────


def cogtainer_key(key: str) -> str:
    """Return ``cogtainer/{COGTAINER}/{key}``."""
    cogtainer = os.environ.get("COGTAINER", "")
    if not cogtainer:
        raise RuntimeError("COGTAINER env var not set")
    return f"cogtainer/{cogtainer}/{key}"


def cogent_key(cogent_name: str, key: str) -> str:
    """Return ``cogent/{cogent_name}/{key}``."""
    return f"cogent/{cogent_name}/{key}"


# ── Local implementation ─────────────────────────────────────


class LocalSecretsProvider:
    """Reads/writes secrets from a JSON file at ``{data_dir}/.secrets.json``."""

    def __init__(self, data_dir: str) -> None:
        self._path = Path(data_dir) / ".secrets.json"

    def get_secret(self, key: str, field: str | None = None) -> str:
        data = self._load()
        if key not in data:
            raise KeyError(key)
        value = data[key]
        if field is not None:
            extracted = _extract_field(value, field, key)
            if extracted is None:
                raise KeyError(f"{key}[{field}]")
            return extracted
        return value

    def set_secret(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._path.write_text(json.dumps(data, indent=2))

    def list_secrets(self, prefix: str) -> list[str]:
        secrets = self._load()
        return [k for k in secrets if k.startswith(prefix)]

    def delete_secret(self, key: str) -> None:
        secrets = self._load()
        secrets.pop(key, None)
        self._path.write_text(json.dumps(secrets, indent=2))

    def cogtainer_secret(self, key: str, field: str | None = None) -> str:
        return self.get_secret(cogtainer_key(key), field=field)

    def cogent_secret(self, cogent_name: str, key: str, field: str | None = None) -> str:
        return self.get_secret(cogent_key(cogent_name, key), field=field)

    # -- private --

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())


# ── AWS implementation ───────────────────────────────────────


class AwsSecretsProvider:
    """SSM Parameter Store with Secrets Manager fallback."""

    def __init__(
        self,
        region: str = "us-east-1",
        session: Any = None,
    ) -> None:
        if session is None:
            import boto3
            session = boto3.Session(region_name=region)
        self._session = session
        self._region = region
        self._sm_client = None
        self._ssm_client = None
        self._cache: dict[str, str] = {}
        self._negative_cache: set[str] = set()

    def get_secret(self, key: str, field: str | None = None) -> str:
        """Try Secrets Manager first, then SSM Parameter Store."""
        if key in self._negative_cache:
            raise KeyError(key)
        if key in self._cache:
            value = self._cache[key]
        else:
            value = self._try_secrets_manager(key)
            if value is None:
                value = self._try_ssm(key)
            if value is None:
                self._negative_cache.add(key)
                raise KeyError(key)
            self._cache[key] = value
        if field is not None:
            extracted = _extract_field(value, field, key)
            if extracted is None:
                raise KeyError(f"{key}[{field}]")
            return extracted
        return value

    def set_secret(self, key: str, value: str) -> None:
        """Write to Secrets Manager."""
        if self._sm_client is None:
            self._sm_client = self._session.client("secretsmanager", region_name=self._region)
        try:
            self._sm_client.put_secret_value(SecretId=key, SecretString=value)
        except self._sm_client.exceptions.ResourceNotFoundException:
            self._sm_client.create_secret(Name=key, SecretString=value)
        self._cache[key] = value
        self._negative_cache.discard(key)

    def list_secrets(self, prefix: str) -> list[str]:
        if self._sm_client is None:
            self._sm_client = self._session.client("secretsmanager", region_name=self._region)
        keys: list[str] = []
        paginator = self._sm_client.get_paginator("list_secrets")
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for secret in page.get("SecretList", []):
                keys.append(secret["Name"])
        return keys

    def delete_secret(self, key: str) -> None:
        if self._sm_client is None:
            self._sm_client = self._session.client("secretsmanager", region_name=self._region)
        self._sm_client.delete_secret(SecretId=key, ForceDeleteWithoutRecovery=True)
        self._cache.pop(key, None)
        self._negative_cache.add(key)

    def cogtainer_secret(self, key: str, field: str | None = None) -> str:
        return self.get_secret(cogtainer_key(key), field=field)

    def cogent_secret(self, cogent_name: str, key: str, field: str | None = None) -> str:
        return self.get_secret(cogent_key(cogent_name, key), field=field)

    # -- private --

    def _try_ssm(self, key: str) -> str | None:
        try:
            if self._ssm_client is None:
                self._ssm_client = self._session.client("ssm", region_name=self._region)
            resp = self._ssm_client.get_parameter(Name=key, WithDecryption=True)
            return resp["Parameter"]["Value"]
        except Exception:
            return None

    def _try_secrets_manager(self, key: str) -> str | None:
        try:
            if self._sm_client is None:
                self._sm_client = self._session.client("secretsmanager", region_name=self._region)
            resp = self._sm_client.get_secret_value(SecretId=key)
            return resp["SecretString"]
        except Exception:
            return None


# ── Factory ──────────────────────────────────────────────────


def create_secrets_provider(
    provider_type: str,
    data_dir: str | None = None,
    region: str | None = None,
    session: Any = None,
) -> SecretsProvider:
    """Instantiate a SecretsProvider by type name."""
    if provider_type in ("local", "docker"):
        if data_dir is None:
            raise ValueError("data_dir is required for local provider")
        return LocalSecretsProvider(data_dir=data_dir)
    if provider_type == "aws":
        return AwsSecretsProvider(
            region=region or "us-east-1",
            session=session,
        )
    raise ValueError(f"Unknown secrets provider type: {provider_type!r}")
