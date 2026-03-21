"""HTTP capability client — proxies capability calls to the CogOS API.

Remote executors use this instead of direct capability instantiation.
Each proxy object mirrors the local capability interface: calling
``data.query(sql)`` transparently becomes ``POST /api/v1/capabilities/data/query``.

Usage::

    from cogos.capabilities.http_client import HttpCapabilityClient

    client = HttpCapabilityClient(api_url="https://api.example.com", token="<jwt>")
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

    def __init__(self, api_url: str, token: str, cap_name: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._cap_name = cap_name

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

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
    """Client for the CogOS API — creates proxies for each capability.

    Also supports creating sessions from an executor key::

        client = HttpCapabilityClient.from_executor_key(
            api_url="https://api.example.com",
            executor_key="...",
            process_id="<uuid>",
        )
    """

    def __init__(self, api_url: str, token: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._proxies: dict[str, HttpCapabilityProxy] = {}

    @classmethod
    def from_executor_key(
        cls,
        api_url: str,
        executor_key: str,
        process_id: str,
        cogent: str = "",
    ) -> HttpCapabilityClient:
        """Bootstrap a client by obtaining a session token from the API."""
        url = f"{api_url.rstrip('/')}/api/v1/sessions"
        resp = httpx.post(
            url,
            json={"process_id": process_id, "cogent": cogent},
            headers={"X-Executor-Key": executor_key, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json()["token"]
        return cls(api_url, token)

    def get(self, cap_name: str) -> HttpCapabilityProxy:
        """Get a proxy for a capability by grant name."""
        if cap_name not in self._proxies:
            self._proxies[cap_name] = HttpCapabilityProxy(self._api_url, self._token, cap_name)
        return self._proxies[cap_name]

    def list_capabilities(self) -> list[dict]:
        """List capabilities available to the current session."""
        url = f"{self._api_url}/api/v1/capabilities"
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("capabilities", [])

    def session_info(self) -> dict:
        """Introspect the current session."""
        url = f"{self._api_url}/api/v1/sessions/me"
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def __repr__(self) -> str:
        return f"<HttpCapabilityClient {self._api_url}>"
