"""Shared secret fetching — delegates to SecretsProvider."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def fetch_secret(key: str, field: str | None = None, *, secrets_provider=None) -> str:
    """Fetch a secret value via the runtime's SecretsProvider.

    If `key` contains ``{cogent}``, it is replaced with the ``COGENT_NAME``
    environment variable.

    If `secrets_provider` is not given, reconstructs one from env vars.
    """
    # Resolve {cogent} placeholder
    if "{cogent}" in key:
        cogent_name = os.environ.get("COGENT_NAME", "")
        if not cogent_name:
            raise RuntimeError(
                f"Secret key '{key}' contains {{cogent}} but COGENT_NAME env var is not set"
            )
        key = key.replace("{cogent}", cogent_name)

    if secrets_provider is None:
        from cogtainer.secrets import create_secrets_provider

        provider_type = os.environ.get("SECRETS_PROVIDER", "aws")
        data_dir = os.environ.get("SECRETS_DATA_DIR", os.environ.get("COGOS_LOCAL_DATA", ""))
        region = os.environ.get("AWS_REGION", "us-east-1")
        secrets_provider = create_secrets_provider(
            provider_type=provider_type,
            data_dir=data_dir,
            region=region,
        )

    try:
        return secrets_provider.get_secret(key, field=field)
    except KeyError as exc:
        raise RuntimeError(f"Could not fetch secret '{key}': {exc}") from exc
