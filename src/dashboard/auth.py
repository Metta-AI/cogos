"""Dashboard API authentication — optional API key verification.

When DASHBOARD_API_KEY (or the corresponding Secrets Manager secret) is set,
all dashboard API routes require a valid ``x-api-key`` header. When no key is
configured the dependency is a no-op so local development works unchanged.
"""

from __future__ import annotations

import logging
import os

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_cached_api_key: str | None = None


def _load_api_key() -> str:
    """Load the dashboard API key from env or Secrets Manager. Returns "" if none configured."""
    global _cached_api_key
    if _cached_api_key is not None:
        return _cached_api_key

    env_key = os.environ.get("DASHBOARD_API_KEY")
    if env_key:
        _cached_api_key = env_key
        return _cached_api_key

    cogent_name = os.environ.get("COGENT", "")
    if cogent_name:
        try:
            import json

            import boto3

            region = os.environ.get("AWS_REGION", "us-east-1")
            sm = boto3.client("secretsmanager", region_name=region)
            secret_id = f"cogent/{cogent_name}/dashboard-api-key"
            resp = sm.get_secret_value(SecretId=secret_id)
            data = json.loads(resp["SecretString"])
            _cached_api_key = str(data.get("api_key", ""))
            return _cached_api_key
        except Exception:
            logger.warning("Could not load dashboard API key from Secrets Manager", exc_info=True)

    _cached_api_key = ""
    return _cached_api_key


def verify_dashboard_api_key(x_api_key: str = Header(default="")) -> None:
    """FastAPI dependency — enforce API key when one is configured.

    If no API key is configured (local dev), all requests pass through.
    """
    expected = _load_api_key()
    if not expected:
        # No key configured — allow all (local dev / unconfigured)
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
