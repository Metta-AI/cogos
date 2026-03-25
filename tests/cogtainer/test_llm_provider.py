"""Tests for cogtainer LLM provider abstraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogtainer.config import LLMConfig
from cogtainer.llm.provider import create_provider

# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_provider_factory_bedrock():
    config = LLMConfig(provider="bedrock", model="us.anthropic.claude-sonnet-4-5-20250929-v1:0", api_key_env="")
    provider = create_provider(config, region="us-east-1")
    from cogtainer.llm.bedrock import BedrockProvider
    assert isinstance(provider, BedrockProvider)


def test_provider_factory_openrouter():
    config = LLMConfig(provider="openrouter", model="anthropic/claude-sonnet-4-5", api_key_env="OPENROUTER_API_KEY")
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test-key"}):
        provider = create_provider(config, region="us-east-1")
    from cogtainer.llm.openrouter import OpenRouterProvider
    assert isinstance(provider, OpenRouterProvider)


def test_provider_factory_anthropic():
    pytest.importorskip("anthropic")
    config = LLMConfig(provider="anthropic", model="claude-sonnet-4-5-20250929", api_key_env="ANTHROPIC_API_KEY")
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}):
        provider = create_provider(config, region="us-east-1")
    from cogtainer.llm.anthropic_provider import AnthropicProvider
    assert isinstance(provider, AnthropicProvider)


def test_provider_factory_unknown_raises():
    config = LLMConfig(provider="gpt-magic", model="gpt-5", api_key_env="")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_provider(config, region="us-east-1")


# ---------------------------------------------------------------------------
# BedrockProvider delegation test
# ---------------------------------------------------------------------------


def test_bedrock_converse_delegates():
    from cogtainer.llm.bedrock import BedrockProvider

    mock_client = MagicMock()
    expected = {
        "output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }
    mock_client.converse.return_value = expected

    provider = BedrockProvider(default_model="us.anthropic.claude-sonnet-4-5-20250929-v1:0", client=mock_client)
    result = provider.converse(
        messages=[{"role": "user", "content": [{"text": "hello"}]}],
        system=[{"text": "Be helpful"}],
        tool_config={},
    )

    assert result == expected
    mock_client.converse.assert_called_once()
    call_kwargs = mock_client.converse.call_args[1]
    assert call_kwargs["modelId"] == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert call_kwargs["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]
    assert call_kwargs["system"] == [{"text": "Be helpful"}]


# ---------------------------------------------------------------------------
# OpenRouterProvider format test
# ---------------------------------------------------------------------------


def test_openrouter_converse_format():
    from cogtainer.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(default_model="anthropic/claude-sonnet-4-5", api_key="sk-test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 3,
        },
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = provider.converse(
            messages=[{"role": "user", "content": [{"text": "hi"}]}],
            system=[{"text": "Be helpful"}],
            tool_config={
                "tools": [
                    {
                        "toolSpec": {
                            "name": "get_weather",
                            "description": "Get weather",
                            "inputSchema": {"json": {"type": "object", "properties": {}}},
                        }
                    }
                ]
            },
        )

    # Verify request format
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["model"] == "anthropic/claude-sonnet-4-5"
    # System message should be first
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "Be helpful"
    # User message follows
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"] == "hi"
    # Tools in OpenAI format
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "get_weather"

    # Verify response is Bedrock-formatted
    assert result["output"]["message"]["role"] == "assistant"
    assert result["output"]["message"]["content"] == [{"text": "Hello!"}]
    assert result["stopReason"] == "end_turn"
    assert result["usage"]["inputTokens"] == 15
    assert result["usage"]["outputTokens"] == 3
