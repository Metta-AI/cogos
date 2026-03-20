"""Tests for LLMClient — Bedrock primary, Anthropic API fallback."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from cogos.executor.llm_client import (
    LLMClient,
    _anthropic_response_to_bedrock,
    _bedrock_messages_to_anthropic,
    _bedrock_model_to_anthropic,
    _bedrock_tools_to_anthropic,
    _resolve_anthropic_api_key,
)

# ── Model ID conversion ──────────────────────────────────────


def test_known_model_mapping():
    assert _bedrock_model_to_anthropic("us.anthropic.claude-sonnet-4-5-20250929-v1:0") == "claude-sonnet-4-5-20250929"


def test_unknown_model_strips_prefix_and_suffix():
    assert _bedrock_model_to_anthropic("us.anthropic.claude-future-v9:0") == "claude-future-v9"


def test_model_without_prefix_passes_through():
    assert _bedrock_model_to_anthropic("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5-20250929"


# ── Tool config conversion ───────────────────────────────────


def test_bedrock_tools_to_anthropic():
    tool_config = {
        "tools": [
            {
                "toolSpec": {
                    "name": "search",
                    "description": "Search things",
                    "inputSchema": {"json": {"type": "object", "properties": {"q": {"type": "string"}}}},
                }
            }
        ]
    }
    result = _bedrock_tools_to_anthropic(tool_config)
    assert len(result) == 1
    assert result[0]["name"] == "search"
    assert result[0]["input_schema"]["type"] == "object"


# ── Message conversion ───────────────────────────────────────


def test_text_message_conversion():
    messages = [{"role": "user", "content": [{"text": "hello"}]}]
    result = _bedrock_messages_to_anthropic(messages)
    assert result == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]


def test_tool_use_message_conversion():
    messages = [
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": "test"}}},
            ],
        }
    ]
    result = _bedrock_messages_to_anthropic(messages)
    block = result[0]["content"][0]
    assert block["type"] == "tool_use"
    assert block["id"] == "t1"
    assert block["name"] == "search"


def test_tool_result_message_conversion():
    messages = [
        {
            "role": "user",
            "content": [
                {"toolResult": {"toolUseId": "t1", "content": [{"text": "result"}]}},
            ],
        }
    ]
    result = _bedrock_messages_to_anthropic(messages)
    block = result[0]["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "t1"


# ── Response conversion ──────────────────────────────────────


@dataclass
class _FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class _FakeTextBlock:
    type: str = "text"
    text: str = "hello"


@dataclass
class _FakeToolUseBlock:
    type: str = "tool_use"
    id: str = "t1"
    name: str = "search"
    input: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.input is None:
            self.input = {"q": "test"}


@dataclass
class _FakeResponse:
    content: list = None  # type: ignore[assignment]
    stop_reason: str = "end_turn"
    usage: _FakeUsage = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.content is None:
            self.content = [_FakeTextBlock()]
        if self.usage is None:
            self.usage = _FakeUsage()


def test_anthropic_text_response_to_bedrock():
    resp = _FakeResponse()
    result = _anthropic_response_to_bedrock(resp)
    assert result["output"]["message"]["content"] == [{"text": "hello"}]
    assert result["stopReason"] == "end_turn"
    assert result["usage"]["inputTokens"] == 10


def test_anthropic_tool_use_response_to_bedrock():
    resp = _FakeResponse(
        content=[_FakeToolUseBlock()],
        stop_reason="tool_use",
    )
    result = _anthropic_response_to_bedrock(resp)
    block = result["output"]["message"]["content"][0]
    assert "toolUse" in block
    assert block["toolUse"]["name"] == "search"
    assert result["stopReason"] == "tool_use"


# ── LLMClient fallback behavior ─────────────────────────────


def _throttling_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "Converse",
    )


def test_llm_client_uses_bedrock_when_not_throttled():
    fake_bedrock = MagicMock()
    fake_bedrock.converse.return_value = {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}}
    client = LLMClient(bedrock_client=fake_bedrock)
    result = client.converse(modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0", messages=[], system=[])
    assert result["output"]["message"]["content"][0]["text"] == "ok"
    fake_bedrock.converse.assert_called_once()


def test_llm_client_raises_throttling_without_anthropic_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "cogos.executor.llm_client._resolve_anthropic_api_key",
        lambda explicit_key=None, secrets_provider=None: None,
    )
    fake_bedrock = MagicMock()
    fake_bedrock.converse.side_effect = _throttling_error()
    client = LLMClient(bedrock_client=fake_bedrock)
    # No anthropic key → should re-raise
    with pytest.raises(ClientError):
        client.converse(modelId="test", messages=[], system=[])


def test_llm_client_falls_back_to_anthropic_on_throttle():
    fake_bedrock = MagicMock()
    fake_bedrock.converse.side_effect = _throttling_error()

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create.return_value = _FakeResponse()

    client = LLMClient(bedrock_client=fake_bedrock)
    client._anthropic = fake_anthropic_client

    result = client.converse(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "You are helpful."}],
        toolConfig={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hello"
    fake_anthropic_client.messages.create.assert_called_once()


# ── API key resolution ────────────────────────────────────────


def test_resolve_explicit_key():
    assert _resolve_anthropic_api_key("sk-explicit") == "sk-explicit"


def test_resolve_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert _resolve_anthropic_api_key() == "sk-env"


def test_resolve_from_secrets(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = MagicMock()
    provider.get_secret.return_value = "sk-secret"
    assert _resolve_anthropic_api_key(secrets_provider=provider) == "sk-secret"


def test_resolve_returns_none_when_nothing_available(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No secrets_provider → returns None
    assert _resolve_anthropic_api_key() is None


def test_llm_client_non_fallback_error_propagates():
    """Errors not in _FALLBACK_ERROR_CODES should propagate without fallback."""
    fake_bedrock = MagicMock()
    fake_bedrock.converse.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "forbidden"}},
        "Converse",
    )
    client = LLMClient(bedrock_client=fake_bedrock)
    client._anthropic = MagicMock()  # Even with fallback available
    with pytest.raises(ClientError):
        client.converse(modelId="test", messages=[], system=[])


def test_llm_client_falls_back_on_validation_exception():
    """ValidationException (e.g. context too long) should trigger Anthropic fallback."""
    fake_bedrock = MagicMock()
    fake_bedrock.converse.side_effect = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Input is too long"}},
        "Converse",
    )

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create.return_value = _FakeResponse()

    client = LLMClient(bedrock_client=fake_bedrock)
    client._anthropic = fake_anthropic_client

    result = client.converse(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "You are helpful."}],
        toolConfig={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hello"
    fake_anthropic_client.messages.create.assert_called_once()


def test_llm_client_falls_back_on_service_unavailable():
    """ServiceUnavailableException should trigger Anthropic fallback."""
    fake_bedrock = MagicMock()
    fake_bedrock.converse.side_effect = ClientError(
        {"Error": {"Code": "ServiceUnavailableException", "Message": "try later"}},
        "Converse",
    )

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create.return_value = _FakeResponse()

    client = LLMClient(bedrock_client=fake_bedrock)
    client._anthropic = fake_anthropic_client

    result = client.converse(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "You are helpful."}],
        toolConfig={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hello"
    fake_anthropic_client.messages.create.assert_called_once()


# ── Anthropic-primary mode ──────────────────────────────────


def _make_anthropic_primary_client(fake_bedrock, fake_anthropic_client):
    """Create an LLMClient in anthropic-primary mode without requiring the anthropic package."""
    client = LLMClient(bedrock_client=fake_bedrock)
    client._provider = "anthropic"
    client._anthropic = fake_anthropic_client
    return client


def test_anthropic_primary_uses_anthropic_first():
    fake_bedrock = MagicMock()
    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create.return_value = _FakeResponse()

    client = _make_anthropic_primary_client(fake_bedrock, fake_anthropic_client)

    result = client.converse(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "You are helpful."}],
        toolConfig={"tools": []},
    )
    assert result["output"]["message"]["content"][0]["text"] == "hello"
    fake_anthropic_client.messages.create.assert_called_once()
    fake_bedrock.converse.assert_not_called()


def test_anthropic_primary_falls_back_to_bedrock_on_error():
    fake_bedrock = MagicMock()
    fake_bedrock.converse.return_value = {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}}

    fake_anthropic_client = MagicMock()
    fake_anthropic_client.messages.create.side_effect = Exception("rate limit")

    client = _make_anthropic_primary_client(fake_bedrock, fake_anthropic_client)

    result = client.converse(
        modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "You are helpful."}],
    )
    assert result["output"]["message"]["content"][0]["text"] == "ok"
    fake_bedrock.converse.assert_called_once()


def test_anthropic_primary_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "cogos.executor.llm_client._resolve_anthropic_api_key",
        lambda explicit_key=None, secrets_provider=None: None,
    )
    with pytest.raises(RuntimeError, match="LLM_PROVIDER=anthropic"):
        LLMClient(bedrock_client=MagicMock(), provider="anthropic")
