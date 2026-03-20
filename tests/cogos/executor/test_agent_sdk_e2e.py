"""End-to-end test: run a simple capability set through the Agent SDK executor.

Requires AWS credentials for Bedrock (set CLAUDE_CODE_USE_BEDROCK=1).
Skip with: pytest -m "not e2e"
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.base import Capability


class MemoryStub(Capability):
    def __init__(self, repo, process_id, **kwargs):
        super().__init__(repo, process_id, **kwargs)
        self._store: dict = {}

    def _narrow(self, existing, requested):
        return {**existing, **requested}

    def _check(self, op, **ctx):
        pass

    def get(self, key: str) -> dict:
        """Get a value from memory."""
        return {"key": key, "value": self._store.get(key, "(not found)")}

    def put(self, key: str, value: str) -> dict:
        """Store a value in memory."""
        self._store[key] = value
        return {"key": key, "status": "saved"}


@pytest.mark.e2e
@pytest.mark.skipif(
    not os.environ.get("CLAUDE_CODE_USE_BEDROCK") and not os.environ.get("ANTHROPIC_API_KEY"),
    reason="Set CLAUDE_CODE_USE_BEDROCK=1 (with AWS creds) or ANTHROPIC_API_KEY",
)
def test_agent_sdk_e2e():
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    from cogos.executor.agent_sdk import build_mcp_server, build_tool_functions

    repo = MagicMock()
    pid = uuid4()
    cap = MemoryStub(repo, pid)
    caps = {"memory": cap}

    server = build_mcp_server(caps)
    tools = build_tool_functions(caps)
    tool_names = [f"mcp__cogent__{t.__tool_name__}" for t in tools]

    options = ClaudeAgentOptions(
        mcp_servers={"cogent": server},
        allowed_tools=tool_names,
        permission_mode="bypassPermissions",
        max_turns=5,
        system_prompt="You have a memory tool. Store the value 'hello world' under key 'test', then read it back and confirm.",
        model="claude-sonnet-4-5",
    )

    result_msg = None

    async def run():
        nonlocal result_msg
        async for msg in query(prompt="Do your task.", options=options):
            if isinstance(msg, ResultMessage):
                result_msg = msg

    asyncio.run(run())

    assert result_msg is not None
    assert result_msg.subtype == "success"
    assert result_msg.total_cost_usd is not None
    assert cap._store.get("test") == "hello world"
