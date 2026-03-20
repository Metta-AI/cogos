"""Shared secret fetching — delegates to SecretsProvider."""
from __future__ import annotations

import os


def fetch_secret(key: str, field: str | None = None, *, secrets_provider: object) -> str:
    """Fetch a secret value via the given SecretsProvider.

    If `key` contains ``{cogent}``, it is replaced with the ``COGENT_NAME``
    environment variable.

    Raises RuntimeError if the secret is not found.
    """
    if "{cogent}" in key:
        cogent_name = os.environ.get("COGENT_NAME", "")
        if not cogent_name:
            raise RuntimeError(
                f"Secret key '{key}' contains {{cogent}} but COGENT_NAME env var is not set"
            )
        key = key.replace("{cogent}", cogent_name)

    try:
        return secrets_provider.get_secret(key, field=field)
    except KeyError as exc:
        raise RuntimeError(f"Could not fetch secret '{key}': {exc}") from exc
