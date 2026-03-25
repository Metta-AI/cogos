"""Tests for runtime factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.runtime.factory import create_runtime
from cogtainer.runtime.local import LocalRuntime


def _make_entry(entry_type: str, **kwargs) -> CogtainerEntry:
    return CogtainerEntry(
        type=entry_type,
        region="us-east-1",
        llm=LLMConfig(provider="anthropic", model="claude-3", api_key_env="ANTHROPIC_API_KEY"),
        **kwargs,
    )


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("cogtainer.llm.anthropic_provider.AnthropicProvider")
def test_create_local_runtime(mock_provider, tmp_path):
    entry = _make_entry("local", data_dir=str(tmp_path))
    runtime = create_runtime(entry)
    assert isinstance(runtime, LocalRuntime)


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("cogtainer.llm.anthropic_provider.AnthropicProvider")
def test_create_docker_runtime(mock_provider, tmp_path):
    entry = _make_entry("docker", data_dir=str(tmp_path))
    runtime = create_runtime(entry)
    assert isinstance(runtime, LocalRuntime)


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("cogtainer.llm.anthropic_provider.AnthropicProvider")
def test_create_unknown_type_raises(mock_provider):
    entry = _make_entry("quantum")
    with pytest.raises(ValueError, match="Unknown cogtainer type: quantum"):
        create_runtime(entry)
