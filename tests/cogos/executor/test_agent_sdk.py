"""Tests for Agent SDK tool generation from CogOS capabilities."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.base import Capability


class StubCapability(Capability):
    """Test capability with typed methods for tool generation."""

    def _narrow(self, existing: dict, requested: dict) -> dict:
        return {**existing, **requested}

    def _check(self, op: str, **context: object) -> None:
        allowed = self._scope.get("ops")
        if allowed is not None and op not in allowed:
            raise PermissionError(f"'{op}' not permitted")

    def get(self, key: str) -> dict:
        """Get a value by key."""
        return {"key": key, "value": "test"}

    def put(self, key: str, value: str) -> dict:
        """Store a value."""
        return {"key": key, "status": "saved"}


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestGetPublicMethods:
    def test_returns_public_methods_only(self, repo, pid):
        from cogos.executor.agent_sdk import get_public_methods

        cap = StubCapability(repo, pid)
        methods = dict(get_public_methods(cap))
        assert "get" in methods
        assert "put" in methods
        assert "_check" not in methods
        assert "_narrow" not in methods
        assert "help" not in methods
        assert "scope" not in methods


class TestSchemaFromMethod:
    def test_generates_schema_from_typed_method(self, repo, pid):
        from cogos.executor.agent_sdk import schema_from_method

        cap = StubCapability(repo, pid)
        schema = schema_from_method(cap.get)
        assert schema["type"] == "object"
        assert "key" in schema["properties"]
        assert schema["properties"]["key"]["type"] == "string"


class TestBuildToolFunctions:
    def test_tool_names_follow_convention(self, repo, pid):
        from cogos.executor.agent_sdk import build_tool_functions

        caps = {"mem": StubCapability(repo, pid)}
        tools = build_tool_functions(caps)
        names = [t.__tool_name__ for t in tools]
        assert "mem_get" in names
        assert "mem_put" in names

    @pytest.mark.asyncio
    async def test_scoped_capability_blocks_disallowed_ops(self, repo, pid):
        from cogos.executor.agent_sdk import build_tool_functions

        cap = StubCapability(repo, pid).scope(ops={"get"})
        caps = {"mem": cap}
        tools = build_tool_functions(caps)
        put_tool = next(t for t in tools if t.__tool_name__ == "mem_put")

        result = await put_tool({"key": "x", "value": "y"})
        content = result["content"][0]["text"]
        assert "not permitted" in content.lower() or "error" in content.lower()


class TestBuildMcpServer:
    def test_creates_server_with_tools(self, repo, pid):
        from cogos.executor.agent_sdk import build_mcp_server

        caps = {"mem": StubCapability(repo, pid)}
        server = build_mcp_server(caps)
        assert server is not None
