"""Shared secret fetching — delegates to SecretsProvider."""
from __future__ import annotations

import os

from cogtainer.secrets import cogtainer_key


def fetch_secret(key: str, field: str | None = None, *, secrets_provider: object) -> str:
    """Fetch a secret value via the given SecretsProvider.

    If `key` contains ``{cogent}``, it is replaced with the ``COGENT``
    environment variable and falls back to the cogtainer-level secret.

    Raises RuntimeError if the secret is not found.
    """
    fallback_key: str | None = None
    if "{cogent}" in key:
        cogent_name = os.environ.get("COGENT", "")
        if not cogent_name:
            raise RuntimeError(
                f"Secret key '{key}' contains {{cogent}} but COGENT env var is not set"
            )
        # Extract the suffix after "cogent/{cogent}/" for cogtainer fallback
        suffix = key.split("{cogent}/", 1)[-1] if "{cogent}/" in key else None
        key = key.replace("{cogent}", cogent_name)
        if suffix:
            try:
                fallback_key = cogtainer_key(suffix)
            except RuntimeError:
                pass

    try:
        return secrets_provider.get_secret(key, field=field)  # type: ignore[union-attr]
    except (KeyError, RuntimeError):
        pass

    if fallback_key:
        try:
            return secrets_provider.get_secret(fallback_key, field=field)  # type: ignore[union-attr]
        except (KeyError, RuntimeError):
            pass

    raise RuntimeError(f"Could not fetch secret '{key}'")
