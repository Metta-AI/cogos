"""Google service-account authentication and API client helpers."""
from __future__ import annotations

import json
import threading
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from cogos.capabilities._secrets_helper import fetch_secret

SECRET_KEY = "cogent/{cogent}/google"

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
]

_lock = threading.Lock()
_credentials_cache: dict[int, service_account.Credentials] = {}
_service_cache: dict[tuple[int, str, str], Any] = {}


def get_google_credentials(
    secrets_provider: object,
) -> service_account.Credentials:
    """Return cached Google service-account credentials.

    The service-account JSON key is fetched from Secrets Manager once per
    ``secrets_provider`` instance and reused on subsequent calls.
    """
    sp_id = id(secrets_provider)
    creds = _credentials_cache.get(sp_id)
    if creds is not None:
        return creds

    with _lock:
        # Double-check after acquiring lock.
        creds = _credentials_cache.get(sp_id)
        if creds is not None:
            return creds

        sa_json = fetch_secret(SECRET_KEY, secrets_provider=secrets_provider)
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES
        )
        _credentials_cache[sp_id] = creds
        return creds


def get_service(
    service_name: str,
    version: str,
    secrets_provider: object,
) -> Any:
    """Return a cached Google API service client.

    ``service_name`` / ``version`` pairs map to the standard discovery API
    names, e.g. ``("drive", "v3")``, ``("docs", "v1")``,
    ``("sheets", "v4")``, ``("calendar", "v3")``.
    """
    sp_id = id(secrets_provider)
    cache_key = (sp_id, service_name, version)
    svc = _service_cache.get(cache_key)
    if svc is not None:
        return svc

    with _lock:
        svc = _service_cache.get(cache_key)
        if svc is not None:
            return svc

        creds = get_google_credentials(secrets_provider)
        svc = build(service_name, version, credentials=creds)
        _service_cache[cache_key] = svc
        return svc
