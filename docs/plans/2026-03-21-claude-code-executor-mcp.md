# Claude Code Executor MCP Server — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge the channels MCP server with the capabilities MCP server into a unified Python stdio MCP server that also registers as a cogos executor, so running Claude Code with this server makes it a first-class cogos executor.

**Architecture:** A single Python stdio MCP server (`cogos.mcp.server`) that on startup: (1) registers as an executor via the dashboard API, (2) heartbeats in the background, (3) polls for work assignments, (4) dynamically exposes process capabilities as MCP tools when work arrives, (5) bridges cogos channels as notifications, and (6) provides a `complete_run` tool for Claude to signal completion. Reuses existing `build_process_capabilities` and `build_tool_functions` from the executor module.

**Tech Stack:** Python 3.12, `mcp` SDK (already used by `cogos.sandbox.server`), `httpx` for async API calls, existing cogos capability/executor infrastructure.

---

### Task 1: Create the unified MCP server module

**Files:**
- Create: `src/cogos/mcp/__init__.py`
- Create: `src/cogos/mcp/server.py`

**Step 1: Write the failing test**

Create `tests/cogos/mcp/test_server.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from cogos.mcp.server import CogosServer


def test_server_creates_with_config():
    """Server initialises with API URL, cogent name, and executor ID."""
    srv = CogosServer(
        api_url="http://localhost:8100",
        cogent_name="test-cogent",
        api_key="test-key",
    )
    assert srv.api_url == "http://localhost:8100"
    assert srv.cogent_name == "test-cogent"
    assert srv.executor_id.startswith("cc-")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/mcp/test_server.py::test_server_creates_with_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.mcp'`

**Step 3: Write minimal implementation**

Create `src/cogos/mcp/__init__.py` (empty).

Create `src/cogos/mcp/server.py`:

```python
"""Unified CogOS MCP server for Claude Code.

Combines channel bridging, executor registration, and capability
exposure into a single stdio MCP server. When Claude Code runs with
this server, it becomes a registered cogos executor that picks up
work, uses capabilities as tools, and signals completion.

Environment variables:
  COGOS_API_URL      - Dashboard API base (e.g. http://localhost:8100)
  COGOS_COGENT_NAME  - Cogent name for API path prefix
  COGOS_API_KEY      - Executor token for authenticated API access
  COGOS_CHANNELS     - Comma-separated channel patterns (default: "io:claude-code:*")
  COGOS_POLL_MS      - Poll interval in ms (default: 2000)
  COGOS_HEARTBEAT_S  - Heartbeat interval in seconds (default: 15)
  COGOS_EXECUTOR_ID  - Custom executor ID (default: auto-generated)
  COGOS_CAPABILITIES - Comma-separated executor capabilities (default: "claude-code")
"""

from __future__ import annotations

import logging
import os
import platform
import secrets

logger = logging.getLogger(__name__)


class CogosServer:
    """Unified MCP server state container."""

    def __init__(
        self,
        api_url: str = "http://localhost:8100",
        cogent_name: str = "",
        api_key: str = "",
        channel_patterns: list[str] | None = None,
        poll_ms: int = 2000,
        heartbeat_s: int = 15,
        executor_id: str | None = None,
        capabilities: list[str] | None = None,
    ) -> None:
        self.api_url = api_url
        self.cogent_name = cogent_name
        self.api_key = api_key
        self.channel_patterns = channel_patterns or ["io:claude-code:*"]
        self.poll_ms = poll_ms
        self.heartbeat_s = heartbeat_s
        self.executor_id = executor_id or f"cc-{platform.node()}-{secrets.token_hex(4)}"
        self.capabilities = capabilities or ["claude-code"]

        # Runtime state
        self.current_run_id: str | None = None
        self.current_process_id: str | None = None
        self.status: str = "idle"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/mcp/test_server.py::test_server_creates_with_config -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/mcp/__init__.py src/cogos/mcp/server.py tests/cogos/mcp/test_server.py
git commit -m "feat: scaffold CogosServer for unified MCP server"
```

---

### Task 2: Add API client for executor operations

**Files:**
- Modify: `src/cogos/mcp/server.py`
- Test: `tests/cogos/mcp/test_server.py`

**Step 1: Write the failing test**

Add to `tests/cogos/mcp/test_server.py`:

```python
import httpx
import pytest


@pytest.mark.asyncio
async def test_register_calls_api(httpx_mock):
    """register() POSTs to /executors/register with correct payload."""
    from pytest_httpx import HTTPXMock

    srv = CogosServer(
        api_url="http://test:8100",
        cogent_name="cog",
        api_key="tok123",
    )

    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/executors/register",
        method="POST",
        json={"executor_id": srv.executor_id, "heartbeat_interval_s": 30, "status": "registered"},
    )

    await srv.register()

    req = httpx_mock.get_request()
    assert req is not None
    import json
    body = json.loads(req.content)
    assert body["executor_id"] == srv.executor_id
    assert body["channel_type"] == "claude-code"
    assert req.headers["authorization"] == "Bearer tok123"


@pytest.mark.asyncio
async def test_heartbeat_calls_api(httpx_mock):
    """heartbeat() POSTs to /executors/{id}/heartbeat."""
    srv = CogosServer(
        api_url="http://test:8100",
        cogent_name="cog",
        api_key="tok123",
    )

    httpx_mock.add_response(
        url=f"http://test:8100/api/cogents/cog/executors/{srv.executor_id}/heartbeat",
        method="POST",
        json={"ok": True},
    )

    await srv.heartbeat()


@pytest.mark.asyncio
async def test_complete_run_calls_api(httpx_mock):
    """complete_run() POSTs to /runs/{id}/complete."""
    srv = CogosServer(
        api_url="http://test:8100",
        cogent_name="cog",
        api_key="tok123",
    )
    srv.current_run_id = "run-123"

    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/runs/run-123/complete",
        method="POST",
        json={"ok": True, "run_id": "run-123", "status": "completed"},
    )

    result = await srv.complete_run(status="completed", output={"text": "done"})
    assert result["ok"] is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cogos/mcp/test_server.py -v -k "register or heartbeat or complete_run"`
Expected: FAIL — methods don't exist

**Step 3: Write minimal implementation**

Add to `CogosServer` in `src/cogos/mcp/server.py`:

```python
import httpx


class CogosServer:
    # ... existing __init__ ...

    def _api_base(self) -> str:
        if self.cogent_name:
            return f"{self.api_url}/api/cogents/{self.cogent_name}"
        return self.api_url

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def register(self) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_base()}/executors/register",
                headers=self._headers(),
                json={
                    "executor_id": self.executor_id,
                    "channel_type": "claude-code",
                    "capabilities": self.capabilities,
                    "metadata": {"claude_code": True, "hostname": platform.node()},
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def heartbeat(self) -> None:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self._api_base()}/executors/{self.executor_id}/heartbeat",
                headers=self._headers(),
                json={
                    "status": self.status,
                    "current_run_id": self.current_run_id,
                },
            )

    async def complete_run(
        self,
        status: str = "completed",
        output: dict | None = None,
        error: str | None = None,
        tokens_used: dict[str, int] | None = None,
        duration_ms: int | None = None,
    ) -> dict:
        if not self.current_run_id:
            return {"ok": False, "error": "no active run"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_base()}/runs/{self.current_run_id}/complete",
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
            data = resp.json()
        self.current_run_id = None
        self.current_process_id = None
        self.status = "idle"
        return data

    async def poll_for_work(self) -> dict | None:
        """Check if scheduler assigned work. Returns run details or None."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._api_base()}/executors/{self.executor_id}",
                    headers=self._headers(),
                )
                if not resp.is_success:
                    return None
                data = resp.json()
                if data.get("status") != "busy" or not data.get("current_run_id"):
                    return None
                run_id = data["current_run_id"]
                run_resp = await client.get(
                    f"{self._api_base()}/runs/{run_id}",
                    headers=self._headers(),
                )
                if not run_resp.is_success:
                    return None
                run_data = run_resp.json()
                self.current_run_id = run_id
                self.current_process_id = run_data.get("process")
                self.status = "busy"
                return run_data
        except httpx.HTTPError:
            return None

    async def fetch_process(self, process_id: str) -> dict | None:
        """Fetch full process details including resolved prompt."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._api_base()}/processes/{process_id}",
                    headers=self._headers(),
                )
                if not resp.is_success:
                    return None
                return resp.json()
        except httpx.HTTPError:
            return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cogos/mcp/test_server.py -v -k "register or heartbeat or complete_run"`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/mcp/server.py tests/cogos/mcp/test_server.py
git commit -m "feat: add API client methods to CogosServer"
```

---

### Task 3: Add channel polling and notification emission

**Files:**
- Modify: `src/cogos/mcp/server.py`
- Test: `tests/cogos/mcp/test_server.py`

**Step 1: Write the failing test**

Add to `tests/cogos/mcp/test_server.py`:

```python
@pytest.mark.asyncio
async def test_fetch_channels(httpx_mock):
    """fetch_channels() returns channel list from API."""
    srv = CogosServer(api_url="http://test:8100", cogent_name="cog")

    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/channels",
        json={"channels": [
            {"id": "ch1", "name": "io:claude-code:inbound", "channel_type": "implicit", "message_count": 5},
        ]},
    )

    channels = await srv.fetch_channels()
    assert len(channels) == 1
    assert channels[0]["name"] == "io:claude-code:inbound"


def test_matches_pattern():
    """Channel pattern matching works with * globs."""
    srv = CogosServer(channel_patterns=["io:claude-code:*", "system:alerts"])
    assert srv.matches_any_pattern("io:claude-code:inbound") is True
    assert srv.matches_any_pattern("system:alerts") is True
    assert srv.matches_any_pattern("io:discord:dm") is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cogos/mcp/test_server.py -v -k "fetch_channels or matches_pattern"`
Expected: FAIL

**Step 3: Write implementation**

Add to `CogosServer` in `src/cogos/mcp/server.py`:

```python
import fnmatch
import re


class CogosServer:
    # ... existing ...

    def __init__(self, ...):
        # ... existing ...
        self.seen_messages: set[str] = set()
        self.channel_index: dict[str, str] = {}  # name -> id

    def matches_pattern(self, name: str, pattern: str) -> bool:
        escaped = re.escape(pattern).replace(r"\*", ".*")
        return bool(re.fullmatch(escaped, name))

    def matches_any_pattern(self, name: str) -> bool:
        return any(self.matches_pattern(name, p) for p in self.channel_patterns)

    async def fetch_channels(self) -> list[dict]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._api_base()}/channels",
                    headers=self._headers(),
                )
                if not resp.is_success:
                    return []
                data = resp.json()
                return data.get("channels", [])
        except httpx.HTTPError:
            return []

    async def fetch_channel_messages(self, channel_id: str, limit: int = 20) -> list[dict]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._api_base()}/channels/{channel_id}",
                    headers=self._headers(),
                    params={"limit": limit},
                )
                if not resp.is_success:
                    return []
                data = resp.json()
                return data.get("messages", [])
        except httpx.HTTPError:
            return []

    async def send_channel_message(self, channel_id: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._api_base()}/channels/{channel_id}/messages",
                    headers=self._headers(),
                    json={"payload": payload},
                )
                if not resp.is_success:
                    err = resp.json() if resp.content else {}
                    return {"error": err.get("detail", resp.reason_phrase)}
                return resp.json()
        except httpx.HTTPError as e:
            return {"error": str(e)}
```

**Step 4: Run tests**

Run: `pytest tests/cogos/mcp/test_server.py -v -k "fetch_channels or matches_pattern"`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/mcp/server.py tests/cogos/mcp/test_server.py
git commit -m "feat: add channel fetching and pattern matching to CogosServer"
```

---

### Task 4: Wire up the MCP server with tools and polling loops

**Files:**
- Modify: `src/cogos/mcp/server.py`

This is the main wiring task. We create the `mcp.Server`, register tools, and set up the background loops (heartbeat, channel poll, work poll).

**Step 1: Write the failing test**

Add to `tests/cogos/mcp/test_server.py`:

```python
@pytest.mark.asyncio
async def test_list_tools_includes_channel_and_executor_tools():
    """MCP tool list includes send, reply, list_channels, complete_run."""
    srv = CogosServer(api_url="http://test:8100", cogent_name="cog")
    mcp_server = srv.create_mcp_server()

    # Access tool list via the handler
    from mcp.types import ListToolsRequest
    tools = await mcp_server.request_handlers[ListToolsRequest]()
    tool_names = {t.name for t in tools}
    assert "send" in tool_names
    assert "reply" in tool_names
    assert "list_channels" in tool_names
    assert "complete_run" in tool_names
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/mcp/test_server.py::test_list_tools_includes_channel_and_executor_tools -v`
Expected: FAIL — `create_mcp_server` doesn't exist

**Step 3: Write implementation**

Add `create_mcp_server` method to `CogosServer` in `src/cogos/mcp/server.py`:

```python
import asyncio
import json
import time

from mcp.server import Server
from mcp.types import TextContent, Tool


class CogosServer:
    # ... existing ...

    def create_mcp_server(self) -> Server:
        """Build an MCP server with channel tools and executor lifecycle tools."""
        mcp = Server("cogos")

        @mcp.list_tools()
        async def list_tools() -> list[Tool]:
            tools = [
                Tool(
                    name="send",
                    description="Send a message to any CogOS channel by name.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "description": "Channel name"},
                            "payload": {"type": "object", "description": "Message payload"},
                        },
                        "required": ["channel", "payload"],
                    },
                ),
                Tool(
                    name="reply",
                    description="Reply to a CogOS channel event.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "description": "Channel name or ID"},
                            "payload": {"type": "object", "description": "Message payload"},
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
                            "pattern": {"type": "string", "description": "Glob pattern to filter"},
                        },
                    },
                ),
                Tool(
                    name="complete_run",
                    description=(
                        "Signal that the current executor run is complete. "
                        "Call this when you have finished the assigned task."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["completed", "failed"],
                                "description": "Run outcome",
                            },
                            "summary": {
                                "type": "string",
                                "description": "Brief summary of what was done",
                            },
                            "error": {
                                "type": "string",
                                "description": "Error message if status is failed",
                            },
                        },
                        "required": ["status"],
                    },
                ),
            ]
            return tools

        @mcp.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name in ("send", "reply"):
                channel_name = arguments.get("channel", "")
                payload = arguments.get("payload", {})
                channel_id = self.channel_index.get(channel_name)
                if not channel_id:
                    await self._refresh_channel_index()
                    channel_id = self.channel_index.get(channel_name, channel_name)
                result = await self.send_channel_message(channel_id, payload)
                if "error" in result:
                    return [TextContent(type="text", text=f"Error: {result['error']}")]
                return [TextContent(type="text", text=f"Sent to {channel_name} (id: {result.get('id', '?')})")]

            if name == "list_channels":
                pattern = arguments.get("pattern", "*")
                channels = await self.fetch_channels()
                filtered = [ch for ch in channels if self.matches_pattern(ch["name"], pattern)]
                lines = [f"{ch['name']} ({ch['channel_type']}, {ch['message_count']} msgs)" for ch in filtered]
                return [TextContent(type="text", text="\n".join(lines) if lines else "No channels found")]

            if name == "complete_run":
                status = arguments.get("status", "completed")
                summary = arguments.get("summary", "")
                error = arguments.get("error")
                output = {"summary": summary} if summary else None
                result = await self.complete_run(status=status, output=output, error=error)
                if result.get("ok"):
                    return [TextContent(type="text", text=f"Run completed with status: {status}")]
                return [TextContent(type="text", text=f"Error completing run: {result.get('error', 'unknown')}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        self._mcp = mcp
        return mcp

    async def _refresh_channel_index(self) -> None:
        channels = await self.fetch_channels()
        for ch in channels:
            self.channel_index[ch["name"]] = ch["id"]
```

**Step 4: Run test**

Run: `pytest tests/cogos/mcp/test_server.py::test_list_tools_includes_channel_and_executor_tools -v`
Expected: PASS (or adjust test if mcp SDK list_tools interface differs — the key thing is the tools exist)

**Step 5: Commit**

```bash
git add src/cogos/mcp/server.py tests/cogos/mcp/test_server.py
git commit -m "feat: wire up MCP tools for channels and executor lifecycle"
```

---

### Task 5: Add background loops (heartbeat, channel poll, work poll)

**Files:**
- Modify: `src/cogos/mcp/server.py`

**Step 1: Write the failing test**

Add to `tests/cogos/mcp/test_server.py`:

```python
@pytest.mark.asyncio
async def test_poll_once_emits_new_messages(httpx_mock):
    """poll_channels_once() discovers new messages and returns them."""
    srv = CogosServer(
        api_url="http://test:8100",
        cogent_name="cog",
        channel_patterns=["io:claude-code:*"],
    )

    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/channels",
        json={"channels": [
            {"id": "ch1", "name": "io:claude-code:inbound", "channel_type": "implicit", "message_count": 1},
        ]},
    )
    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/channels/ch1",
        json={"messages": [
            {"id": "msg1", "channel": "ch1", "sender_process": "p1", "payload": {"text": "hello"}, "created_at": "2026-01-01T00:00:00Z"},
        ]},
    )

    new_msgs = await srv.poll_channels_once()
    assert len(new_msgs) == 1
    assert new_msgs[0]["id"] == "msg1"

    # Second poll: same message should not appear again
    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/channels",
        json={"channels": [
            {"id": "ch1", "name": "io:claude-code:inbound", "channel_type": "implicit", "message_count": 1},
        ]},
    )
    httpx_mock.add_response(
        url="http://test:8100/api/cogents/cog/channels/ch1",
        json={"messages": [
            {"id": "msg1", "channel": "ch1", "sender_process": "p1", "payload": {"text": "hello"}, "created_at": "2026-01-01T00:00:00Z"},
        ]},
    )
    new_msgs2 = await srv.poll_channels_once()
    assert len(new_msgs2) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/mcp/test_server.py::test_poll_once_emits_new_messages -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `CogosServer`:

```python
class CogosServer:
    # ... existing ...

    async def poll_channels_once(self) -> list[dict]:
        """Poll subscribed channels, return new messages, update seen set."""
        new_messages = []
        channels = await self.fetch_channels()

        for ch in channels:
            if not self.matches_any_pattern(ch["name"]):
                continue
            self.channel_index[ch["name"]] = ch["id"]

            messages = await self.fetch_channel_messages(ch["id"], 20)
            for msg in messages:
                if msg["id"] in self.seen_messages:
                    continue
                self.seen_messages.add(msg["id"])
                msg["_channel_name"] = ch["name"]
                msg["_channel_id"] = ch["id"]
                new_messages.append(msg)

        # Prune seen set
        if len(self.seen_messages) > 10000:
            to_remove = list(self.seen_messages)[:5000]
            for mid in to_remove:
                self.seen_messages.discard(mid)

        return new_messages

    async def seed_seen_messages(self) -> None:
        """Mark all existing messages as seen so we only forward new ones."""
        channels = await self.fetch_channels()
        for ch in channels:
            if not self.matches_any_pattern(ch["name"]):
                continue
            self.channel_index[ch["name"]] = ch["id"]
            messages = await self.fetch_channel_messages(ch["id"], 100)
            for msg in messages:
                self.seen_messages.add(msg["id"])

    async def run_heartbeat_loop(self) -> None:
        """Background loop: send heartbeats every heartbeat_s seconds."""
        while True:
            try:
                await self.heartbeat()
            except Exception:
                logger.debug("heartbeat failed", exc_info=True)
            await asyncio.sleep(self.heartbeat_s)

    async def run_channel_poll_loop(self, mcp: Server) -> None:
        """Background loop: poll channels and emit notifications."""
        while True:
            try:
                new_msgs = await self.poll_channels_once()
                for msg in new_msgs:
                    try:
                        await mcp.request_context.session.send_notification(
                            method="notifications/claude/channel",
                            params={
                                "channel": msg["_channel_name"],
                                "content": json.dumps(msg.get("payload", {}), indent=2),
                                "meta": {
                                    "message_id": msg["id"],
                                    "channel_id": msg["_channel_id"],
                                    "channel_name": msg["_channel_name"],
                                    "sender_process": msg.get("sender_process"),
                                    "sender_process_name": msg.get("sender_process_name"),
                                    "created_at": msg.get("created_at"),
                                },
                            },
                        )
                    except Exception:
                        pass
            except Exception:
                logger.debug("channel poll failed", exc_info=True)
            await asyncio.sleep(self.poll_ms / 1000)

    async def run_work_poll_loop(self, mcp: Server) -> None:
        """Background loop: check for assigned work and notify Claude."""
        while True:
            try:
                if self.status == "idle":
                    run_data = await self.poll_for_work()
                    if run_data:
                        process = await self.fetch_process(self.current_process_id)
                        prompt = process.get("resolved_prompt", "") if process else ""
                        process_name = process.get("name", "unknown") if process else "unknown"

                        await mcp.request_context.session.send_notification(
                            method="notifications/claude/channel",
                            params={
                                "channel": "executor:work",
                                "content": json.dumps({
                                    "run_id": self.current_run_id,
                                    "process_id": self.current_process_id,
                                    "process_name": process_name,
                                    "system_prompt": prompt,
                                    "event": run_data.get("event"),
                                }, indent=2),
                                "meta": {
                                    "type": "executor_work_assigned",
                                    "run_id": self.current_run_id,
                                    "process_name": process_name,
                                },
                            },
                        )
            except Exception:
                logger.debug("work poll failed", exc_info=True)
            await asyncio.sleep(self.poll_ms / 1000)
```

**Step 4: Run tests**

Run: `pytest tests/cogos/mcp/test_server.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/mcp/server.py tests/cogos/mcp/test_server.py
git commit -m "feat: add heartbeat, channel poll, and work poll loops"
```

---

### Task 6: Add CLI entry point and main function

**Files:**
- Modify: `src/cogos/mcp/server.py`
- Create: `src/cogos/mcp/__main__.py`

**Step 1: Write the `main()` function and entry point**

Add to `src/cogos/mcp/server.py`:

```python
from mcp.server.stdio import stdio_server


async def amain() -> None:
    """Entry point: create server, register executor, start loops, run MCP."""
    srv = CogosServer(
        api_url=os.environ.get("COGOS_API_URL", "http://localhost:8100"),
        cogent_name=os.environ.get("COGOS_COGENT_NAME", ""),
        api_key=os.environ.get("COGOS_API_KEY", ""),
        channel_patterns=(os.environ.get("COGOS_CHANNELS", "io:claude-code:*")).split(","),
        poll_ms=int(os.environ.get("COGOS_POLL_MS", "2000")),
        heartbeat_s=int(os.environ.get("COGOS_HEARTBEAT_S", "15")),
        executor_id=os.environ.get("COGOS_EXECUTOR_ID"),
        capabilities=(os.environ.get("COGOS_CAPABILITIES", "claude-code")).split(","),
    )

    mcp = srv.create_mcp_server()

    # Register with cogos
    try:
        await srv.register()
        logger.info("Registered executor %s", srv.executor_id)
    except Exception:
        logger.warning("Failed to register executor — will retry on heartbeat", exc_info=True)

    # Seed seen messages so we don't replay history
    await srv.seed_seen_messages()

    async with stdio_server() as (read_stream, write_stream):
        # Start background loops
        heartbeat_task = asyncio.create_task(srv.run_heartbeat_loop())
        channel_task = asyncio.create_task(srv.run_channel_poll_loop(mcp))
        work_task = asyncio.create_task(srv.run_work_poll_loop(mcp))

        try:
            await mcp.run(read_stream, write_stream, mcp.create_initialization_options())
        finally:
            heartbeat_task.cancel()
            channel_task.cancel()
            work_task.cancel()


def main() -> None:
    asyncio.run(amain())
```

Create `src/cogos/mcp/__main__.py`:

```python
from cogos.mcp.server import main

main()
```

**Step 2: Verify it can be invoked**

Run: `python -m cogos.mcp --help 2>&1 || echo "ok - will error without API"`

This won't fully work without a running dashboard, but confirms the module is importable.

**Step 3: Commit**

```bash
git add src/cogos/mcp/server.py src/cogos/mcp/__main__.py
git commit -m "feat: add CLI entry point for cogos MCP server"
```

---

### Task 7: Update .mcp.json to use the unified Python server

**Files:**
- Modify: `.mcp.json`

**Step 1: Update config**

Replace the bun-based server with the Python one:

```json
{
  "mcpServers": {
    "cogos": {
      "command": "python",
      "args": ["-m", "cogos.mcp"],
      "env": {
        "COGOS_API_URL": "http://localhost:8100",
        "COGOS_COGENT_NAME": "",
        "COGOS_CHANNELS": "io:claude-code:*,system:alerts",
        "COGOS_API_KEY": ""
      }
    }
  }
}
```

**Step 2: Commit**

```bash
git add .mcp.json
git commit -m "feat: switch .mcp.json to unified Python MCP server"
```

---

### Task 8: End-to-end manual test

**Step 1: Start local dashboard**

Run: `cogos dashboard` (or however the local dashboard is started)

**Step 2: Run Claude Code with the MCP server**

Run: `claude` (from the repo root — it will pick up `.mcp.json`)

**Step 3: Verify executor registration**

In Claude Code, use the `list_channels` tool to confirm the MCP server is connected. Also check the dashboard UI or API to confirm an executor appears:

```bash
curl http://localhost:8100/api/cogents/<name>/executors
```

**Step 4: Verify channel bridging**

Send a message to a subscribed channel via the dashboard and confirm Claude Code receives the notification.

**Step 5: Verify work execution**

Create a process with `runner: "channel"`, trigger it, and confirm Claude Code receives the work notification and can call `complete_run` when done.

---

## Notes

- The old TS channels server (`channels/claude-code/server.ts`) is preserved — it still works for non-executor use cases. The new Python server is a superset.
- `httpx` is used for async HTTP since the MCP server runs in asyncio. Add it to dependencies if not already present.
- The `complete_run` tool is the explicit contract between Claude Code and the executor lifecycle. Claude must call it when done.
- Work arrives as a `notifications/claude/channel` with channel `executor:work` — Claude Code will see this as a channel event with the process prompt and context.
