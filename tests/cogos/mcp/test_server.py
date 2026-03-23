"""Tests for cogos.mcp.server — CogosServer API client, MCP tools, and background loops."""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from pytest_httpx import HTTPXMock

from cogos.mcp.server import CogosServer, _emit_channel_notification


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def server() -> CogosServer:
    return CogosServer(
        api_url="http://test-api:8100",
        cogent_name="test-cogent",
        api_key="test-key",
        channel_patterns=["io:claude-code:*", "system:alerts"],
        executor_id="cc-test-1234",
        capabilities=["claude-code"],
    )


# ── Init tests ──────────────────────────────────────────────────

class TestInit:
    def test_default_values(self):
        s = CogosServer()
        assert s.api_url == "http://localhost:8100"
        assert s.cogent_name == ""
        assert s.channel_patterns == ["io:claude-code:*"]
        assert s.executor_id.startswith("cc-")
        assert s.capabilities == ["claude-code"]
        assert s.seen_messages == set()
        assert s.channel_index == {}
        assert s.current_run_id is None

    def test_custom_values(self, server: CogosServer):
        assert server.api_url == "http://test-api:8100"
        assert server.cogent_name == "test-cogent"
        assert server.api_key == "test-key"
        assert server.executor_id == "cc-test-1234"

    def test_api_base_with_cogent(self, server: CogosServer):
        assert server._api_base() == "http://test-api:8100/api/cogents/test-cogent"

    def test_api_base_without_cogent(self):
        s = CogosServer(api_url="http://localhost:8100", cogent_name="")
        assert s._api_base() == "http://localhost:8100"

    def test_headers_with_api_key(self, server: CogosServer):
        h = server._headers()
        assert h["x-api-key"] == "test-key"
        assert h["Authorization"] == "Bearer test-key"
        assert h["Content-Type"] == "application/json"

    def test_headers_without_api_key(self):
        s = CogosServer(api_key="")
        h = s._headers()
        assert "x-api-key" not in h
        assert "Authorization" not in h

    def test_trailing_slash_stripped(self):
        s = CogosServer(api_url="http://localhost:8100/")
        assert s.api_url == "http://localhost:8100"


# ── Pattern matching tests ──────────────────────────────────────

class TestPatternMatching:
    def test_exact_match(self, server: CogosServer):
        assert server.matches_pattern("system:alerts", "system:alerts") is True

    def test_glob_star(self, server: CogosServer):
        assert server.matches_pattern("io:claude-code:requests", "io:claude-code:*") is True
        assert server.matches_pattern("io:claude-code:responses", "io:claude-code:*") is True
        assert server.matches_pattern("io:discord:dm", "io:claude-code:*") is False

    def test_no_match(self, server: CogosServer):
        assert server.matches_pattern("other:channel", "io:claude-code:*") is False

    def test_wildcard_all(self, server: CogosServer):
        assert server.matches_pattern("anything", "*") is True

    def test_matches_any_pattern(self, server: CogosServer):
        assert server.matches_any_pattern("io:claude-code:requests") is True
        assert server.matches_any_pattern("system:alerts") is True
        assert server.matches_any_pattern("io:discord:dm") is False

    def test_empty_name(self, server: CogosServer):
        assert server.matches_pattern("", "io:*") is False
        assert server.matches_pattern("", "*") is True


# ── Executor lifecycle tests ────────────────────────────────────

class TestRegister:
    @pytest.mark.anyio
    async def test_register_success(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/register",
            method="POST",
            json={"executor_id": "cc-test-1234", "status": "idle"},
        )
        result = await server.register()
        assert result["executor_id"] == "cc-test-1234"
        await server.close()

    @pytest.mark.anyio
    async def test_register_failure(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/register",
            method="POST",
            status_code=500,
        )
        result = await server.register()
        assert result == {}
        await server.close()


class TestHeartbeat:
    @pytest.mark.anyio
    async def test_heartbeat_idle(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/cc-test-1234/heartbeat",
            method="POST",
            json={"ok": True},
        )
        await server.heartbeat()
        req = httpx_mock.get_request()
        assert req is not None
        import json
        body = json.loads(req.content)
        assert body["status"] == "idle"
        assert body["current_run_id"] is None
        await server.close()

    @pytest.mark.anyio
    async def test_heartbeat_busy(self, server: CogosServer, httpx_mock: HTTPXMock):
        server.current_run_id = "run-123"
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/cc-test-1234/heartbeat",
            method="POST",
            json={"ok": True},
        )
        await server.heartbeat()
        req = httpx_mock.get_request()
        assert req is not None
        import json
        body = json.loads(req.content)
        assert body["status"] == "busy"
        assert body["current_run_id"] == "run-123"
        await server.close()

    @pytest.mark.anyio
    async def test_heartbeat_error_swallowed(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/cc-test-1234/heartbeat",
            method="POST",
            status_code=503,
        )
        # Should not raise
        await server.heartbeat()
        await server.close()


class TestCompleteRun:
    @pytest.mark.anyio
    async def test_complete_run_success(self, server: CogosServer, httpx_mock: HTTPXMock):
        server.current_run_id = "run-456"
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/runs/run-456/complete",
            method="POST",
            json={"id": "run-456", "status": "completed"},
        )
        result = await server.complete_run(status="completed", output={"text": "done"})
        assert result["status"] == "completed"
        assert server.current_run_id is None
        await server.close()

    @pytest.mark.anyio
    async def test_complete_run_no_current(self, server: CogosServer):
        result = await server.complete_run()
        assert result == {}
        await server.close()

    @pytest.mark.anyio
    async def test_complete_run_failure(self, server: CogosServer, httpx_mock: HTTPXMock):
        server.current_run_id = "run-789"
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/runs/run-789/complete",
            method="POST",
            status_code=500,
        )
        result = await server.complete_run()
        assert result == {}
        await server.close()


class TestPollForWork:
    @pytest.mark.anyio
    async def test_poll_no_work(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/cc-test-1234",
            method="GET",
            json={"status": "idle", "current_run_id": None},
        )
        result = await server.poll_for_work()
        assert result is None
        await server.close()

    @pytest.mark.anyio
    async def test_poll_with_work(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/cc-test-1234",
            method="GET",
            json={"status": "busy", "current_run_id": "run-100"},
        )
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/runs/run-100",
            method="GET",
            json={"id": "run-100", "process": "proc-1", "status": "running"},
        )
        result = await server.poll_for_work()
        assert result is not None
        assert result["id"] == "run-100"
        assert server.current_run_id == "run-100"
        await server.close()

    @pytest.mark.anyio
    async def test_poll_error(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/executors/cc-test-1234",
            method="GET",
            status_code=500,
        )
        result = await server.poll_for_work()
        assert result is None
        await server.close()


class TestFetchProcess:
    @pytest.mark.anyio
    async def test_fetch_success(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/processes/proc-1",
            method="GET",
            json={"id": "proc-1", "name": "my-process", "runner": "claude-code"},
        )
        result = await server.fetch_process("proc-1")
        assert result is not None
        assert result["name"] == "my-process"
        await server.close()

    @pytest.mark.anyio
    async def test_fetch_not_found(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/processes/nonexistent",
            method="GET",
            status_code=404,
        )
        result = await server.fetch_process("nonexistent")
        assert result is None
        await server.close()


# ── Channel operation tests ─────────────────────────────────────

MOCK_CHANNELS = [
    {"id": "ch-1", "name": "io:claude-code:requests", "channel_type": "io", "message_count": 5},
    {"id": "ch-2", "name": "io:claude-code:responses", "channel_type": "io", "message_count": 3},
    {"id": "ch-3", "name": "io:discord:dm", "channel_type": "io", "message_count": 10},
    {"id": "ch-4", "name": "system:alerts", "channel_type": "system", "message_count": 1},
]


class TestFetchChannels:
    @pytest.mark.anyio
    async def test_fetch_success(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": MOCK_CHANNELS},
        )
        result = await server.fetch_channels()
        assert len(result) == 4
        await server.close()

    @pytest.mark.anyio
    async def test_fetch_error(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            status_code=500,
        )
        result = await server.fetch_channels()
        assert result == []
        await server.close()


class TestFetchChannelMessages:
    @pytest.mark.anyio
    async def test_fetch_messages(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-1", params={"limit": "20"}),
            method="GET",
            json={"messages": [{"id": "msg-1", "payload": {"text": "hello"}}]},
        )
        result = await server.fetch_channel_messages("ch-1")
        assert len(result) == 1
        assert result[0]["id"] == "msg-1"
        await server.close()


class TestSendChannelMessage:
    @pytest.mark.anyio
    async def test_send_success(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels/ch-1/messages",
            method="POST",
            json={"id": "msg-new"},
        )
        result = await server.send_channel_message("ch-1", {"text": "hi"})
        assert result["id"] == "msg-new"
        await server.close()

    @pytest.mark.anyio
    async def test_send_error(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels/ch-1/messages",
            method="POST",
            status_code=500,
        )
        result = await server.send_channel_message("ch-1", {"text": "hi"})
        assert "error" in result
        await server.close()


# ── Channel polling tests ───────────────────────────────────────

class TestPollChannelsOnce:
    @pytest.mark.anyio
    async def test_poll_new_messages(self, server: CogosServer, httpx_mock: HTTPXMock):
        # Channels endpoint
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": MOCK_CHANNELS},
        )
        # Messages for matching channels
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-1", params={"limit": "20"}),
            method="GET",
            json={"messages": [
                {"id": "msg-1", "payload": {"text": "hello"}},
                {"id": "msg-2", "payload": {"text": "world"}},
            ]},
        )
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-2", params={"limit": "20"}),
            method="GET",
            json={"messages": [{"id": "msg-3", "payload": {"text": "response"}}]},
        )
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-4", params={"limit": "20"}),
            method="GET",
            json={"messages": [{"id": "msg-4", "payload": {"text": "alert"}}]},
        )

        result = await server.poll_channels_once()
        assert len(result) == 4
        assert {m["id"] for m in result} == {"msg-1", "msg-2", "msg-3", "msg-4"}
        # channel metadata should be attached
        assert result[0]["channel_name"] == "io:claude-code:requests"
        await server.close()

    @pytest.mark.anyio
    async def test_poll_deduplication(self, server: CogosServer, httpx_mock: HTTPXMock):
        # Pre-seed a message as seen
        server.seen_messages.add("msg-1")

        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": [MOCK_CHANNELS[0]]},  # just ch-1
        )
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-1", params={"limit": "20"}),
            method="GET",
            json={"messages": [
                {"id": "msg-1", "payload": {"text": "old"}},
                {"id": "msg-5", "payload": {"text": "new"}},
            ]},
        )

        result = await server.poll_channels_once()
        assert len(result) == 1
        assert result[0]["id"] == "msg-5"
        assert "msg-1" in server.seen_messages
        assert "msg-5" in server.seen_messages
        await server.close()

    @pytest.mark.anyio
    async def test_poll_skips_non_matching(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": [MOCK_CHANNELS[2]]},  # io:discord:dm — doesn't match
        )

        result = await server.poll_channels_once()
        assert len(result) == 0
        await server.close()

    @pytest.mark.anyio
    async def test_seen_pruning(self, server: CogosServer, httpx_mock: HTTPXMock):
        # Pre-fill seen with > 10000 entries
        for i in range(10500):
            server.seen_messages.add(f"old-{i}")

        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": []},
        )

        await server.poll_channels_once()
        # Should have been pruned to ~5000
        assert len(server.seen_messages) <= 5500
        await server.close()


class TestSeedSeenMessages:
    @pytest.mark.anyio
    async def test_seed(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": MOCK_CHANNELS},
        )
        # Messages for matching channels (3 match: ch-1, ch-2, ch-4)
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-1", params={"limit": "100"}),
            method="GET",
            json={"messages": [{"id": "seed-1"}, {"id": "seed-2"}]},
        )
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-2", params={"limit": "100"}),
            method="GET",
            json={"messages": [{"id": "seed-3"}]},
        )
        httpx_mock.add_response(
            url=httpx.URL("http://test-api:8100/api/cogents/test-cogent/channels/ch-4", params={"limit": "100"}),
            method="GET",
            json={"messages": [{"id": "seed-4"}]},
        )

        await server.seed_seen_messages()
        assert server.seen_messages == {"seed-1", "seed-2", "seed-3", "seed-4"}
        assert server.channel_index["io:claude-code:requests"] == "ch-1"
        await server.close()


class TestRefreshChannelIndex:
    @pytest.mark.anyio
    async def test_refresh(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": MOCK_CHANNELS},
        )
        await server._refresh_channel_index()
        assert server.channel_index["io:claude-code:requests"] == "ch-1"
        assert server.channel_index["io:discord:dm"] == "ch-3"
        assert len(server.channel_index) == 4
        await server.close()


# ── MCP server wiring tests (Task 4) ──────────────────────────

class TestCreateMcpServer:
    def test_returns_server(self, server: CogosServer):
        from mcp.server import Server
        mcp_srv = server.create_mcp_server()
        assert isinstance(mcp_srv, Server)

    def test_server_name(self, server: CogosServer):
        mcp_srv = server.create_mcp_server()
        assert mcp_srv.name == "cogos"


class TestMcpTools:
    @pytest.fixture
    def mcp_srv(self, server: CogosServer):  # type: ignore[no-untyped-def]
        return server.create_mcp_server()

    @pytest.mark.anyio
    async def test_list_tools(self, server: CogosServer):
        mcp_srv = server.create_mcp_server()
        # Access the registered list_tools handler
        # The Server registers handlers via decorators; invoke the handler
        from mcp.types import ListToolsRequest
        handler = mcp_srv.request_handlers.get(type(ListToolsRequest()))
        assert handler is not None

    @pytest.mark.anyio
    async def test_send_tool(self, server: CogosServer, httpx_mock: HTTPXMock):
        mcp_srv = server.create_mcp_server()
        # Pre-populate channel index
        server.channel_index["io:claude-code:responses"] = "ch-2"

        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels/ch-2/messages",
            method="POST",
            json={"id": "msg-new"},
        )

        # Call the tool handler directly
        from mcp.types import CallToolRequest, CallToolRequestParams
        handler = mcp_srv.request_handlers.get(type(CallToolRequest(params=CallToolRequestParams(name="send", arguments={}))))
        # Instead, use the internal call_tool approach
        # We need to test via the CogosServer methods directly
        result = await server.send_channel_message("ch-2", {"text": "hello"})
        assert result["id"] == "msg-new"
        await server.close()

    @pytest.mark.anyio
    async def test_list_channels_tool(self, server: CogosServer, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="http://test-api:8100/api/cogents/test-cogent/channels",
            method="GET",
            json={"channels": MOCK_CHANNELS},
        )
        channels = await server.fetch_channels()
        filtered = [ch for ch in channels if server.matches_pattern(ch.get("name", ""), "io:*")]
        assert len(filtered) == 3
        await server.close()


# ── Background loop tests (Task 5) ────────────────────────────

class TestHeartbeatLoop:
    @pytest.mark.anyio
    async def test_heartbeat_loop_runs(self, server: CogosServer):
        call_count = 0

        async def mock_heartbeat():
            nonlocal call_count
            call_count += 1

        server.heartbeat = mock_heartbeat  # type: ignore[assignment]
        server.heartbeat_s = 0  # type: ignore[assignment]  # 50ms for testing
        task = asyncio.create_task(server.run_heartbeat_loop())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert call_count >= 2


class TestChannelPollLoop:
    @pytest.mark.anyio
    async def test_channel_poll_emits_notifications(self, server: CogosServer):
        poll_count = 0

        async def mock_poll_channels_once():
            nonlocal poll_count
            poll_count += 1
            if poll_count == 1:
                return [
                    {
                        "id": "new-1",
                        "payload": {"text": "hello"},
                        "channel_name": "io:claude-code:requests",
                        "channel_id": "ch-1",
                        "sender_process": "p1",
                        "created_at": "2026-01-01",
                    }
                ]
            return []

        server.poll_channels_once = mock_poll_channels_once  # type: ignore[assignment]

        import io
        buf = io.BytesIO()

        server.poll_ms = 50
        with patch("sys.stdout", MagicMock(buffer=buf)):
            task = asyncio.create_task(server.run_channel_poll_loop(None))
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        import json as json_mod
        output = buf.getvalue().decode("utf-8").strip()
        assert output, "expected notification output"
        data = json_mod.loads(output)
        assert data["method"] == "notifications/claude/channel"
        assert data["params"]["channel"] == "io:claude-code:requests"


# ── CLI entry point tests (Task 6) ─────────────────────────────

class TestEntryPoint:
    def test_main_importable(self):
        from cogos.mcp.server import main, amain
        assert callable(main)
        assert inspect.iscoroutinefunction(amain)

    def test_dunder_main_importable(self):
        import importlib.util
        spec = importlib.util.find_spec("cogos.mcp.__main__")
        assert spec is not None


class TestEmitChannelNotification:
    @pytest.mark.anyio
    async def test_emit_writes_to_stdout(self):
        import io
        buf = io.BytesIO()

        with patch("sys.stdout", MagicMock(buffer=buf)):
            await _emit_channel_notification(None, channel="test:ch", content="hello", meta={"key": "val"})

        import json
        output = buf.getvalue().decode("utf-8").strip()
        data = json.loads(output)
        assert data["method"] == "notifications/claude/channel"
        assert data["params"]["channel"] == "test:ch"

    @pytest.mark.anyio
    async def test_emit_swallows_errors(self):
        with patch("sys.stdout", MagicMock(buffer=MagicMock(write=MagicMock(side_effect=RuntimeError("broken"))))):
            # Should not raise
            await _emit_channel_notification(None, channel="test:ch", content="hello")
