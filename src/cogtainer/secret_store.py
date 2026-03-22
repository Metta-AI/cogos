"""SecretStore: direct Secrets Manager access with caching."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import boto3

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes


class SecretStore:
    """Read/write secrets from AWS Secrets Manager with in-memory caching."""

    def __init__(self, session: boto3.Session | None = None, region: str = "us-east-1"):
        self._session = session or boto3.Session()
        self._region = region
        self._client: Any | None = None
        self._cache: dict[str, tuple[dict, float]] = {}
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._session.client("secretsmanager", region_name=self._region)
        return self._client

    def get(self, path: str, *, use_cache: bool = True) -> dict[str, Any]:
        """Fetch and parse a secret value. Returns the parsed JSON dict."""
        now = time.time()
        with self._lock:
            if use_cache and path in self._cache:
                value, expires_at = self._cache[path]
                if expires_at > now:
                    return value

        resp = self.client.get_secret_value(SecretId=path)
        value = json.loads(resp["SecretString"])
        with self._lock:
            self._cache[path] = (value, now + CACHE_TTL)
        return value

    def get_token(self, path: str) -> str:
        """Get the access_token field from a secret."""
        return self.get(path)["access_token"]

    def put(self, path: str, value: dict[str, Any]) -> None:
        """Create or update a secret."""
        secret_string = json.dumps(value)
        try:
            self.client.put_secret_value(SecretId=path, SecretString=secret_string)
        except self.client.exceptions.ResourceNotFoundException:
            self.client.create_secret(Name=path, SecretString=secret_string)
        with self._lock:
            self._cache.pop(path, None)
        logger.info("Stored secret: %s", path)

    def delete(self, path: str) -> None:
        """Delete a secret."""
        self.client.delete_secret(SecretId=path, ForceDeleteWithoutRecovery=True)
        with self._lock:
            self._cache.pop(path, None)
        logger.info("Deleted secret: %s", path)

    def list(self, prefix: str) -> list[str]:
        """List secret names matching a prefix."""
        names: list[str] = []
        paginator = self.client.get_paginator("list_secrets")
        for page in paginator.paginate(
            Filters=[{"Key": "name", "Values": [prefix]}],
        ):
            for s in page["SecretList"]:
                names.append(s["Name"])
        return sorted(names)

    def invalidate(self, path: str | None = None) -> None:
        """Clear cache for a specific path, or all if path is None."""
        with self._lock:
            if path:
                self._cache.pop(path, None)
            else:
                self._cache.clear()
