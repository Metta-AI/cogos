"""LLM client with Bedrock-primary, Anthropic API fallback on throttling."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Bedrock cross-region model ID prefix → Anthropic model name
_BEDROCK_TO_ANTHROPIC_MODEL: dict[str, str] = {
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "claude-sonnet-4-5-20250929",
    "us.anthropic.claude-sonnet-4-20250514-v1:0": "claude-sonnet-4-20250514",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "claude-haiku-4-5-20251001",
    "us.anthropic.claude-opus-4-5-20250430-v1:0": "claude-opus-4-5-20250430",
    "us.anthropic.claude-opus-4-6-20260610-v1:0": "claude-opus-4-6-20260610",
    "us.anthropic.claude-sonnet-4-6-20260610-v1:0": "claude-sonnet-4-6-20260610",
}


def _bedrock_model_to_anthropic(model_id: str) -> str:
    """Convert a Bedrock model ID to an Anthropic API model name."""
    if model_id in _BEDROCK_TO_ANTHROPIC_MODEL:
        return _BEDROCK_TO_ANTHROPIC_MODEL[model_id]
    # Strip common prefixes: "us.anthropic." and trailing ":0"
    name = model_id
    for prefix in ("us.anthropic.", "anthropic."):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.endswith(":0"):
        name = name[:-2]
    return name


def _bedrock_tools_to_anthropic(tool_config: dict) -> list[dict]:
    """Convert Bedrock toolConfig to Anthropic tools format."""
    tools = []
    for tool in tool_config.get("tools", []):
        spec = tool.get("toolSpec", {})
        schema = spec.get("inputSchema", {}).get("json", {})
        tools.append({
            "name": spec["name"],
            "description": spec.get("description", ""),
            "input_schema": schema,
        })
    return tools


def _bedrock_messages_to_anthropic(messages: list[dict]) -> list[dict]:
    """Convert Bedrock converse messages to Anthropic format."""
    result = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", [])
        anthropic_content = []
        for block in content:
            if "text" in block:
                anthropic_content.append({"type": "text", "text": block["text"]})
            elif "toolUse" in block:
                tu = block["toolUse"]
                anthropic_content.append({
                    "type": "tool_use",
                    "id": tu["toolUseId"],
                    "name": tu["name"],
                    "input": tu.get("input", {}),
                })
            elif "toolResult" in block:
                tr = block["toolResult"]
                tr_content = []
                for c in tr.get("content", []):
                    if "text" in c:
                        tr_content.append({"type": "text", "text": c["text"]})
                    elif "json" in c:
                        tr_content.append({"type": "text", "text": json.dumps(c["json"])})
                anthropic_content.append({
                    "type": "tool_result",
                    "tool_use_id": tr["toolUseId"],
                    "content": tr_content,
                })
            elif "image" in block:
                img = block["image"]
                anthropic_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.get("format", "image/png"),
                        "data": img.get("source", {}).get("bytes", ""),
                    },
                })
        result.append({"role": role, "content": anthropic_content})
    return result


def _anthropic_response_to_bedrock(response: Any) -> dict:
    """Convert Anthropic Messages API response to Bedrock converse format."""
    content = []
    for block in response.content:
        if block.type == "text":
            content.append({"text": block.text})
        elif block.type == "tool_use":
            content.append({
                "toolUse": {
                    "toolUseId": block.id,
                    "name": block.name,
                    "input": block.input,
                },
            })

    stop_reason_map = {
        "end_turn": "end_turn",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "stop_sequence": "end_turn",
    }

    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": content,
            },
        },
        "stopReason": stop_reason_map.get(response.stop_reason, "end_turn"),
        "usage": {
            "inputTokens": response.usage.input_tokens,
            "outputTokens": response.usage.output_tokens,
        },
    }


ANTHROPIC_SECRET_PATH = "cogent/polis/anthropic"


def _resolve_anthropic_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve Anthropic API key: explicit arg > env var > polis secret."""
    if explicit_key:
        return explicit_key
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    try:
        from cogos.capabilities._secrets_helper import fetch_secret
        return fetch_secret(ANTHROPIC_SECRET_PATH, field="api_key")
    except Exception as exc:
        logger.debug("Could not fetch Anthropic key from secrets: %s", exc)
        return None


class LLMClient:
    """Wraps Bedrock converse with Anthropic API support.

    When provider='anthropic', uses Anthropic API as primary with Bedrock fallback.
    When provider='bedrock' (default), uses Bedrock as primary with Anthropic
    fallback on throttling.

    Key resolution order: explicit arg > ANTHROPIC_API_KEY env var >
    cogent/polis/anthropic secret.
    """

    def __init__(
        self,
        *,
        bedrock_client: Any | None = None,
        region: str = "us-east-1",
        anthropic_api_key: str | None = None,
        provider: str = "bedrock",
    ) -> None:
        self._provider = provider
        self._bedrock = bedrock_client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
        )
        api_key = _resolve_anthropic_api_key(anthropic_api_key)
        self._anthropic = None
        if api_key:
            try:
                import anthropic
                self._anthropic = anthropic.Anthropic(api_key=api_key)
                logger.info("Anthropic API %s", "primary" if provider == "anthropic" else "fallback enabled")
            except ImportError:
                logger.warning("anthropic package not installed — Anthropic API disabled")
        if provider == "anthropic" and self._anthropic is None:
            raise RuntimeError("LLM_PROVIDER=anthropic but no API key found and/or anthropic package not installed")

    def converse(self, **kwargs: Any) -> dict:
        if self._provider == "anthropic":
            return self._converse_anthropic_primary(**kwargs)
        return self._converse_bedrock_primary(**kwargs)

    # Bedrock error codes that should trigger Anthropic fallback.
    _FALLBACK_ERROR_CODES = {"ThrottlingException", "ValidationException", "ServiceUnavailableException", "ResourceNotFoundException"}

    def _converse_bedrock_primary(self, **kwargs: Any) -> dict:
        """Bedrock primary, Anthropic fallback on throttling or validation errors."""
        try:
            return self._bedrock.converse(**kwargs)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code not in self._FALLBACK_ERROR_CODES or self._anthropic is None:
                raise
            logger.warning(
                "Bedrock %s (model=%s), falling back to Anthropic API",
                error_code,
                kwargs.get("modelId"),
            )
            try:
                return self._call_anthropic(**kwargs)
            except Exception as fallback_exc:
                logger.warning("Anthropic fallback failed: %s", fallback_exc)
                raise exc from fallback_exc

    def _converse_anthropic_primary(self, **kwargs: Any) -> dict:
        """Anthropic primary, Bedrock fallback on error."""
        try:
            return self._call_anthropic(**kwargs)
        except Exception as exc:
            logger.warning(
                "Anthropic API failed (model=%s, error=%s), falling back to Bedrock",
                kwargs.get("modelId"),
                exc,
            )
            return self._bedrock.converse(**kwargs)

    def _call_anthropic(self, **kwargs: Any) -> dict:
        """Translate Bedrock converse kwargs → Anthropic Messages API call."""
        assert self._anthropic is not None
        model = _bedrock_model_to_anthropic(kwargs["modelId"])
        messages = _bedrock_messages_to_anthropic(kwargs["messages"])

        system_blocks = kwargs.get("system", [])
        system_text = "\n\n".join(b["text"] for b in system_blocks if "text" in b)

        tools = _bedrock_tools_to_anthropic(kwargs.get("toolConfig", {}))

        api_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 16384,
            "messages": messages,
        }
        if system_text:
            api_kwargs["system"] = system_text
        if tools:
            api_kwargs["tools"] = tools

        response = self._anthropic.messages.create(**api_kwargs)
        return _anthropic_response_to_bedrock(response)
