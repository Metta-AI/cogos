"""Shared secret fetching — delegates to SecretsProvider."""
from __future__ import annotations

import os


def fetch_secret(key: str, field: str | None = None, *, secrets_provider: object) -> str:
    """Fetch a secret value via the given SecretsProvider.

    If `key` contains ``{cogent}``, it is replaced with the ``COGENT``
    environment variable.

    Raises RuntimeError if the secret is not found.
    """
    fallback_key: str | None = None
    if "{cogent}" in key:
        cogent_name = os.environ.get("COGENT", "")
        if not cogent_name:
            raise RuntimeError(
                f"Secret key '{key}' contains {{cogent}} but COGENT env var is not set"
            )
        fallback_key = key.replace("{cogent}", "all")
        key = key.replace("{cogent}", cogent_name)

    try:
        return secrets_provider.get_secret(key, field=field)
    except (KeyError, RuntimeError):
        pass

    if fallback_key:
        try:
            return secrets_provider.get_secret(fallback_key, field=field)
        except (KeyError, RuntimeError):
            pass

    raise RuntimeError(f"Could not fetch secret '{key}'")
