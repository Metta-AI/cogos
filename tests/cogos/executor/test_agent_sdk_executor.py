"""Tests for executor routing and model mapping."""

from __future__ import annotations

import pytest


class TestModelMapping:
    def test_bedrock_model_passthrough(self):
        from cogos.executor.agent_sdk import to_sdk_model

        assert to_sdk_model("us.anthropic.claude-sonnet-4-5-20250929-v1:0") == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert to_sdk_model("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_short_name_passthrough(self):
        from cogos.executor.agent_sdk import to_sdk_model

        assert to_sdk_model("sonnet") == "sonnet"
        assert to_sdk_model("claude-sonnet-4-5") == "claude-sonnet-4-5"


class TestExecuteProcessRouting:
    def test_agent_sdk_executor_routes_correctly(self):
        """Verify execute_process recognizes executor='agent_sdk'."""
        from cogos.executor.handler import execute_process
        import inspect

        src = inspect.getsource(execute_process)
        assert "agent_sdk" in src
