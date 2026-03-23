"""CogOS API client library for executor lifecycle and channel operations."""

from __future__ import annotations

import fnmatch
import logging
import platform
import secrets
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class CogosServer:
    """Client for the CogOS dashboard API supporting executor lifecycle and channel operations.

    Provides methods for:
    - Executor registration, heartbeat, work polling, and run completion
    - Channel listing, message fetching, sending, and polling with deduplication
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8100",
        cogent_name: str = "",
        api_key: str = "",
        channel_patterns: list[str] | None = None,
        poll_ms: int = 3000,
        heartbeat_s: int = 15,
        executor_id: str | None = None,
        executor_tags: list[str] | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.cogent_name = cogent_name
        self.api_key = api_key
        self.channel_patterns = channel_patterns or ["io:claude-code:*"]
        self.poll_ms = poll_ms
        self.heartbeat_s = heartbeat_s
        self.executor_id = executor_id or f"cc-{platform.node()}-{secrets.token_hex(4)}"
        self.executor_tags = executor_tags or ["claude-code"]

        # Channel state
        self.seen_messages: set[str] = set()
        self.channel_index: dict[str, str] = {}  # name -> id

        # Current run tracking
        self.current_run_id: str | None = None

        # HTTP client (lazy-initialized)
        self._client: httpx.AsyncClient | None = None

    # ── Internal helpers ────────────────────────────────────────

    def _api_base(self) -> str:
        if self.cogent_name:
            return f"{self.api_url}/api/cogents/{self.cogent_name}"
        return self.api_url

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Executor lifecycle ───────────────────────────────────────

    async def register(self) -> dict[str, Any]:
        """Register this executor with the dashboard API.

        POST /api/cogents/{name}/executors/register
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self._api_base()}/executors/register",
                headers=self._headers(),
                json={
                    "executor_id": self.executor_id,
                    "channel_type": "claude-code",
                    "executor_tags": self.executor_tags,
                    "dispatch_type": "channel",
                    "metadata": {"mcp": True, "hostname": platform.node()},
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Subscribe to the executor's dedicated channel
            executor_channel = data.get("channel", "")
            if executor_channel:
                self.channel_patterns.append(executor_channel)
                logger.info("Subscribed to executor channel %s", executor_channel)

            return data
        except Exception:
            logger.debug("register failed", exc_info=True)
            return {}

    async def heartbeat(self) -> None:
        """Send a heartbeat for this executor.

        POST /api/cogents/{name}/executors/{id}/heartbeat
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self._api_base()}/executors/{self.executor_id}/heartbeat",
                headers=self._headers(),
                json={
                    "status": "busy" if self.current_run_id else "idle",
                    "current_run_id": self.current_run_id,
                },
            )
            resp.raise_for_status()
        except Exception:
            logger.debug("heartbeat failed", exc_info=True)

    async def complete_run(
        self,
        status: str = "completed",
        output: dict[str, Any] | None = None,
        error: str | None = None,
        tokens_used: dict[str, int] | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Mark the current run as complete.

        POST /api/cogents/{name}/runs/{id}/complete
        """
        if not self.current_run_id:
            return {}
        run_id = self.current_run_id
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self._api_base()}/runs/{run_id}/complete",
                headers=self._headers(),
                json={
                    "executor_id": self.executor_id,
                    "status": status,
                    "output": output,
                    "error": error,
                    "tokens_used": tokens_used,
                    "duration_ms": duration_ms,
                },
            )
            resp.raise_for_status()
            self.current_run_id = None
            return resp.json()
        except Exception:
            logger.debug("complete_run failed", exc_info=True)
            return {}

    async def poll_for_work(self) -> dict[str, Any] | None:
        """Check if this executor has been assigned work.

        GET /api/cogents/{name}/executors/{id}
        If status==busy and current_run_id is set, fetches the run details.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self._api_base()}/executors/{self.executor_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "busy" or not data.get("current_run_id"):
                return None

            run_id = data["current_run_id"]
            run_resp = await client.get(
                f"{self._api_base()}/runs/{run_id}",
                headers=self._headers(),
            )
            run_resp.raise_for_status()
            run_data = run_resp.json()
            self.current_run_id = run_id
            return run_data
        except Exception:
            logger.debug("poll_for_work failed", exc_info=True)
            return None

    async def fetch_process(self, process_id: str) -> dict[str, Any] | None:
        """Fetch process details.

        GET /api/cogents/{name}/processes/{id}
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self._api_base()}/processes/{process_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.debug("fetch_process failed", exc_info=True)
            return None

    # ── Channel operations ───────────────────────────────────────

    def matches_pattern(self, name: str, pattern: str) -> bool:
        """Check if a channel name matches an fnmatch-style glob pattern."""
        return fnmatch.fnmatch(name, pattern)

    def matches_any_pattern(self, name: str) -> bool:
        """Check if a channel name matches any of the configured patterns."""
        return any(self.matches_pattern(name, p) for p in self.channel_patterns)

    async def fetch_channels(self) -> list[dict[str, Any]]:
        """Fetch all channels from the API.

        GET /api/cogents/{name}/channels
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self._api_base()}/channels",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("channels", [])
        except Exception:
            logger.debug("fetch_channels failed", exc_info=True)
            return []

    async def fetch_channel_messages(
        self, channel_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Fetch recent messages from a channel.

        GET /api/cogents/{name}/channels/{id}?limit=N
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self._api_base()}/channels/{channel_id}",
                headers=self._headers(),
                params={"limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("messages", [])
        except Exception:
            logger.debug("fetch_channel_messages failed", exc_info=True)
            return []

    async def send_channel_message(
        self, channel_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a message to a channel.

        POST /api/cogents/{name}/channels/{id}/messages
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self._api_base()}/channels/{channel_id}/messages",
                headers=self._headers(),
                json={"payload": payload},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("send_channel_message failed", exc_info=True)
            return {"error": str(e)}

    async def poll_channels_once(self) -> list[dict[str, Any]]:
        """Poll all matching channels for new messages.

        Returns a list of new messages (not previously seen) with channel metadata attached.
        Prunes the seen set if it exceeds 10000 entries.
        """
        new_messages: list[dict[str, Any]] = []
        channels = await self.fetch_channels()

        for ch in channels:
            ch_name = ch.get("name", "")
            ch_id = ch.get("id", "")
            if not self.matches_any_pattern(ch_name):
                continue

            # Update channel index
            self.channel_index[ch_name] = ch_id

            messages = await self.fetch_channel_messages(ch_id, 20)
            for msg in messages:
                msg_id = msg.get("id", "")
                if not msg_id or msg_id in self.seen_messages:
                    continue
                self.seen_messages.add(msg_id)
                new_messages.append(
                    {
                        **msg,
                        "channel_name": ch_name,
                        "channel_id": ch_id,
                    }
                )

        # Prune seen set to prevent unbounded growth
        if len(self.seen_messages) > 10000:
            excess = len(self.seen_messages) - 5000
            it = iter(self.seen_messages)
            to_remove = [next(it) for _ in range(excess)]
            for item in to_remove:
                self.seen_messages.discard(item)

        return new_messages

    async def seed_seen_messages(self) -> None:
        """Seed the seen set with existing messages so we only forward new ones.

        Called once at startup to avoid replaying history.
        """
        channels = await self.fetch_channels()
        for ch in channels:
            ch_name = ch.get("name", "")
            ch_id = ch.get("id", "")
            if not self.matches_any_pattern(ch_name):
                continue
            self.channel_index[ch_name] = ch_id
            messages = await self.fetch_channel_messages(ch_id, 100)
            for msg in messages:
                msg_id = msg.get("id", "")
                if msg_id:
                    self.seen_messages.add(msg_id)

    async def _refresh_channel_index(self) -> None:
        """Refresh the channel name -> id mapping."""
        channels = await self.fetch_channels()
        for ch in channels:
            ch_name = ch.get("name", "")
            ch_id = ch.get("id", "")
            if ch_name and ch_id:
                self.channel_index[ch_name] = ch_id
