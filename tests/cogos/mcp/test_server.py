"""Tests for cogos.mcp.server — CogosServer API client."""

from __future__ import annotations

import json

import pytest
import httpx
from pytest_httpx import HTTPXMock

from cogos.mcp.server import CogosServer


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
