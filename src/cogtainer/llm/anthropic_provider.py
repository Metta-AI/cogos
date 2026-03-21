"""Anthropic LLM provider — reuses converters from cogos.executor.llm_client."""

from __future__ import annotations

from typing import Any

from cogtainer.llm.provider import LLMProvider


class AnthropicProvider(LLMProvider):
    """Calls the Anthropic Messages API, returning Bedrock-format responses."""

    def __init__(self, default_model: str = "", api_key: str = "") -> None:
        super().__init__(default_model=default_model)
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        from cogos.executor.llm_client import (
            _anthropic_response_to_bedrock,
            _bedrock_messages_to_anthropic,
            _bedrock_model_to_anthropic,
            _bedrock_tools_to_anthropic,
        )

        model_name = model or self._default_model
        model_name = _bedrock_model_to_anthropic(model_name)
        anth_messages = _bedrock_messages_to_anthropic(messages)
        system_text = "\n\n".join(b["text"] for b in system if "text" in b)
        tools = _bedrock_tools_to_anthropic(tool_config)

        api_kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": 16384,
            "messages": anth_messages,
        }
        if system_text:
            api_kwargs["system"] = system_text
        if tools:
            api_kwargs["tools"] = tools

        response = self._client.messages.create(**api_kwargs)
        return _anthropic_response_to_bedrock(response)
