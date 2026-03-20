"""Tests for LocalRuntime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.runtime.local import LocalRuntime


@pytest.fixture()
def local_runtime(tmp_path: Path) -> LocalRuntime:
    entry = CogtainerEntry(type="local", data_dir=str(tmp_path), llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""))
    llm = MagicMock()
    return LocalRuntime(entry=entry, llm=llm)


# ── Repository ───────────────────────────────────────────────


def test_local_runtime_get_repository(local_runtime: LocalRuntime, tmp_path: Path):
    from cogos.db.local_repository import LocalRepository

    repo = local_runtime.get_repository("alpha")
    assert isinstance(repo, LocalRepository)
    # Data dir should be under the cogent subdirectory
    assert (tmp_path / "alpha").is_dir()


# ── File storage ─────────────────────────────────────────────


def test_local_runtime_file_storage(local_runtime: LocalRuntime):
    data = b"hello world"
    key = local_runtime.put_file("beta", "greet.txt", data)
    assert key == "greet.txt"

    result = local_runtime.get_file("beta", "greet.txt")
    assert result == data


# ── LLM delegation ──────────────────────────────────────────


def test_local_runtime_converse_delegates(local_runtime: LocalRuntime):
    expected = {"output": {"message": {"role": "assistant", "content": []}}}
    mock_llm = cast(MagicMock, local_runtime._llm)
    mock_llm.converse.return_value = expected

    result = local_runtime.converse(
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "sys"}],
        tool_config={},
    )

    assert result == expected
    mock_llm.converse.assert_called_once_with(
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "sys"}],
        tool_config={},
        model=None,
    )


# ── Cogent lifecycle ────────────────────────────────────────


def test_local_runtime_list_cogents(local_runtime: LocalRuntime):
    assert local_runtime.list_cogents() == []

    local_runtime.create_cogent("one")
    local_runtime.create_cogent("two")
    assert local_runtime.list_cogents() == ["one", "two"]

    local_runtime.destroy_cogent("one")
    assert local_runtime.list_cogents() == ["two"]
