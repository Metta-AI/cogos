"""Unified CogOS MCP server — API client, MCP tools, background loops, and CLI entry point."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import platform
import secrets
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, TextContent, Tool

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
        capabilities: list[str] | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.cogent_name = cogent_name
        self.api_key = api_key
        self.channel_patterns = channel_patterns or ["io:claude-code:*"]
        self.poll_ms = poll_ms
        self.heartbeat_s = heartbeat_s
        self.executor_id = executor_id or f"cc-{platform.node()}-{secrets.token_hex(4)}"
        self.capabilities = capabilities or ["claude-code"]

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

    # ── Executor lifecycle (Task 2) ─────────────────────────────

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
                    "capabilities": self.capabilities,
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

    # ── Channel operations (Task 3) ─────────────────────────────

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

    # ── MCP server wiring (Task 4) ──────────────────────────────

    def create_mcp_server(self) -> Server:
        """Create an MCP Server with send, reply, list_channels, and complete_run tools."""
        mcp_server = Server("cogos", instructions=(
            "You are connected to CogOS. Messages from the cogent will arrive as "
            "<channel> events on your executor channel. Use the reply tool to respond."
        ))
        cogos = self

        @mcp_server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="send",
                    description="Send a message to any CogOS channel by name.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel": {
                                "type": "string",
                                "description": "Channel name (e.g. 'system:alerts', 'io:discord:dm')",
                            },
                            "payload": {
                                "type": "object",
                                "description": "Message payload",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["channel", "payload"],
                    },
                ),
                Tool(
                    name="reply",
                    description="Send a message back to a CogOS channel. Use this to respond to channel events.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel": {
                                "type": "string",
                                "description": "Channel name (e.g. 'io:claude-code:responses') or channel ID",
                            },
                            "payload": {
                                "type": "object",
                                "description": "Message payload (must match channel schema if defined)",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["channel", "payload"],
                    },
                ),
                Tool(
                    name="list_channels",
                    description="List available CogOS channels and their message counts.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Optional glob pattern to filter channels (e.g. 'io:*', 'system:*')",
                            },
                        },
                    },
                ),
                Tool(
                    name="complete_run",
                    description="Signal that the current executor run is complete.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["completed", "failed"],
                                "description": "Run completion status",
                            },
                            "summary": {
                                "type": "string",
                                "description": "Optional summary of what was accomplished",
                            },
                            "error": {
                                "type": "string",
                                "description": "Optional error message if status is failed",
                            },
                        },
                        "required": ["status"],
                    },
                ),
            ]

        @mcp_server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name in ("send", "reply"):
                channel_name_or_id: str = arguments["channel"]
                payload: dict[str, Any] = arguments["payload"]

                # Resolve channel name to ID
                channel_id = cogos.channel_index.get(channel_name_or_id)
                if not channel_id:
                    await cogos._refresh_channel_index()
                    channel_id = cogos.channel_index.get(channel_name_or_id) or channel_name_or_id

                result = await cogos.send_channel_message(channel_id, payload)
                if "error" in result:
                    return [TextContent(type="text", text=f"Error sending to {channel_name_or_id}: {result['error']}")]
                return [TextContent(type="text", text=f"Message sent to {channel_name_or_id} (id: {result.get('id', 'unknown')})")]

            if name == "list_channels":
                pattern = arguments.get("pattern", "*")
                channels = await cogos.fetch_channels()
                filtered = [ch for ch in channels if cogos.matches_pattern(ch.get("name", ""), pattern)]
                lines = [
                    f"{ch.get('name', '?')} ({ch.get('channel_type', '?')}, {ch.get('message_count', 0)} msgs)"
                    for ch in filtered
                ]
                text = "\n".join(lines) if lines else "No channels found"
                return [TextContent(type="text", text=text)]

            if name == "complete_run":
                status = arguments["status"]
                summary = arguments.get("summary")
                error = arguments.get("error")
                output = {"summary": summary} if summary else None
                result = await cogos.complete_run(status=status, output=output, error=error)
                if not result:
                    return [TextContent(type="text", text="No active run to complete")]
                return [TextContent(type="text", text=f"Run completed with status: {status}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return mcp_server

    # ── Background loops (Task 5) ────────────────────────────────

    async def run_heartbeat_loop(self) -> None:
        """Send heartbeats at regular intervals. Swallows all errors."""
        while True:
            try:
                await self.heartbeat()
            except Exception:
                logger.debug("heartbeat loop error", exc_info=True)
            await asyncio.sleep(self.heartbeat_s)

    async def run_channel_poll_loop(self, write_stream: Any) -> None:
        """Poll channels for new messages and emit MCP notifications."""
        import sys
        while True:
            try:
                new_messages = await self.poll_channels_once()
                if new_messages:
                    print(f"[cogos-mcp] polled {len(new_messages)} new messages", file=sys.stderr)
                for msg in new_messages:
                    print(f"[cogos-mcp] emitting notification for {msg.get('channel_name')}", file=sys.stderr)
                    await _emit_channel_notification(
                        write_stream,
                        channel=msg.get("channel_name", ""),
                        content=json.dumps(msg.get("payload", {}), indent=2),
                        meta={
                            "message_id": msg.get("id", ""),
                            "channel_id": msg.get("channel_id", ""),
                            "channel_name": msg.get("channel_name", ""),
                            "sender_process": msg.get("sender_process", ""),
                            "sender_process_name": msg.get("sender_process_name"),
                            "created_at": msg.get("created_at", ""),
                        },
                    )
                    print(f"[cogos-mcp] notification sent successfully", file=sys.stderr)
            except Exception as e:
                print(f"[cogos-mcp] poll error: {e}", file=sys.stderr)
            await asyncio.sleep(self.poll_ms / 1000)

    async def run_work_poll_loop(self, mcp_server: Server) -> None:
        """Poll for executor work assignments and emit MCP notifications when work arrives."""
        while True:
            try:
                if not self.current_run_id:
                    run_data = await self.poll_for_work()
                    if run_data:
                        process_id = run_data.get("process") or run_data.get("process_id", "")
                        process_data = await self.fetch_process(process_id) if process_id else None
                        content_parts = [f"New run assigned: {run_data.get('id', '')}"]
                        if process_data:
                            content_parts.append(f"Process: {process_data.get('name', process_id)}")
                            if process_data.get("system_prompt"):
                                content_parts.append(f"System prompt: {process_data['system_prompt']}")
                        await _emit_channel_notification(
                            mcp_server,
                            channel="executor:work",
                            content="\n".join(content_parts),
                            meta={
                                "run_id": run_data.get("id", ""),
                                "process_id": process_id,
                                "process": process_data,
                            },
                        )
            except Exception:
                logger.debug("work poll loop error", exc_info=True)
            await asyncio.sleep(self.poll_ms / 1000)


# ── Notification helper ─────────────────────────────────────────

async def _emit_channel_notification(
    write_stream: Any,
    channel: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> None:
    """Send a custom notifications/claude/channel JSON-RPC notification.

    Writes directly to stdout as a JSON-RPC line, bypassing the MCP session's
    write stream to avoid blocking on the zero-buffer memory channel.
    """
    import sys
    try:
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/claude/channel",
            "params": {
                "channel": channel,
                "content": content,
                "meta": meta or {},
            },
        }
        line = json.dumps(notification) + "\n"
        sys.stdout.buffer.write(line.encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        logger.debug("failed to emit channel notification", exc_info=True)


# ── CLI entry point (Task 6) ────────────────────────────────────

async def amain() -> None:
    """Async main: create CogOS server, register, seed, run MCP server with background loops."""
    api_url = os.environ.get("COGOS_API_URL", "http://localhost:8100")
    cogent_name = os.environ.get("COGENT", "")
    api_key = os.environ.get("COGOS_API_KEY", "")
    channels = os.environ.get("COGOS_CHANNELS", "io:claude-code:*")
    poll_ms = int(os.environ.get("COGOS_POLL_MS", "3000"))
    heartbeat_s = int(os.environ.get("COGOS_HEARTBEAT_S", "15"))
    executor_id = os.environ.get("COGOS_EXECUTOR_ID") or None
    capabilities_str = os.environ.get("COGOS_CAPABILITIES", "claude-code")
    capabilities = [c.strip() for c in capabilities_str.split(",") if c.strip()]

    channel_patterns = [p.strip() for p in channels.split(",") if p.strip()]

    cogos = CogosServer(
        api_url=api_url,
        cogent_name=cogent_name,
        api_key=api_key,
        channel_patterns=channel_patterns,
        poll_ms=poll_ms,
        heartbeat_s=heartbeat_s,
        executor_id=executor_id,
        capabilities=capabilities,
    )

    mcp_srv = cogos.create_mcp_server()

    import sys
    # Register executor
    result = await cogos.register()
    print(f"[cogos-mcp] registered: {result}", file=sys.stderr)
    print(f"[cogos-mcp] channel_patterns: {cogos.channel_patterns}", file=sys.stderr)

    # Seed seen messages to avoid replaying history
    await cogos.seed_seen_messages()
    print(f"[cogos-mcp] seeded {len(cogos.seen_messages)} seen messages", file=sys.stderr)

    # Run MCP server with background loops
    async with stdio_server() as (read_stream, write_stream):
        # Start background tasks
        tasks: list[asyncio.Task[None]] = []
        tasks.append(asyncio.create_task(cogos.run_heartbeat_loop()))
        tasks.append(asyncio.create_task(cogos.run_channel_poll_loop(write_stream)))

        try:
            init_options = mcp_srv.create_initialization_options(
                experimental_capabilities={"claude/channel": {}},
            )
            await mcp_srv.run(read_stream, write_stream, init_options)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await cogos.close()


def main() -> None:
    """Synchronous entry point."""
    asyncio.run(amain())
