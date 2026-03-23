"""HTTP capability client -- proxies capability calls to the CogOS API.

Remote executors use this instead of direct capability instantiation.
Each proxy object mirrors the local capability interface: calling
``data.query(sql)`` transparently becomes ``POST /api/v1/capabilities/data/query``.

Usage::

    from cogos.capabilities.http_client import HttpCapabilityClient

    client = HttpCapabilityClient.from_token(
        api_url="https://api.example.com",
        token="<bearer-token>",
        process_id="<uuid>",
    )
    data = client.get("data")       # returns HttpCapabilityProxy
    result = data.query("SELECT 1") # calls POST /api/v1/capabilities/data/query
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HttpCapabilityProxy:
    """Proxies capability method calls to the CogOS API over HTTP."""

    def __init__(self, api_url: str, token: str, cap_name: str, process_id: str = "") -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._cap_name = cap_name
        self._process_id = process_id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        if self._process_id:
            headers["X-Process-Id"] = self._process_id
        return headers

    def __getattr__(self, method_name: str) -> Any:
        if method_name.startswith("_"):
            raise AttributeError(method_name)

        def _invoke(**kwargs: Any) -> Any:
            url = f"{self._api_url}/api/v1/capabilities/{self._cap_name}/{method_name}"
            payload: dict[str, Any] = {"args": kwargs}
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise RuntimeError(f"{self._cap_name}.{method_name}: {data['error']}")
            return data.get("result")

        return _invoke

    def help(self) -> str:
        """Fetch help text from the API."""
        url = f"{self._api_url}/api/v1/capabilities/{self._cap_name}"
        resp = httpx.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("help", "")

    def __repr__(self) -> str:
        return f"<HttpCapabilityProxy {self._cap_name}>"


class HttpCapabilityClient:
    """Client for the CogOS API -- creates proxies for each capability.

    Use ``from_token`` to create a client with a Bearer token and process ID::

        client = HttpCapabilityClient.from_token(
            api_url="https://api.example.com",
            token="<bearer-token>",
            process_id="<uuid>",
        )
    """

    def __init__(self, api_url: str, token: str, process_id: str = "") -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._process_id = process_id
        self._proxies: dict[str, HttpCapabilityProxy] = {}

    @classmethod
    def from_token(
        cls,
        api_url: str,
        token: str,
        process_id: str,
    ) -> HttpCapabilityClient:
        """Create a client with a Bearer token and process ID."""
        return cls(api_url, token, process_id)

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._process_id:
            headers["X-Process-Id"] = self._process_id
        return headers

    def get(self, cap_name: str) -> HttpCapabilityProxy:
        """Get a proxy for a capability by grant name."""
        if cap_name not in self._proxies:
            self._proxies[cap_name] = HttpCapabilityProxy(
                self._api_url, self._token, cap_name, self._process_id,
            )
        return self._proxies[cap_name]

    def list_capabilities(self) -> list[dict]:
        """List capabilities available to the current session."""
        url = f"{self._api_url}/api/v1/capabilities"
        resp = httpx.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("capabilities", [])

    def __repr__(self) -> str:
        return f"<HttpCapabilityClient {self._api_url}>"
