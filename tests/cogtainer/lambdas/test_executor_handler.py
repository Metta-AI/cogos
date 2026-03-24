"""Tests for the executor Lambda handler — repo obtained via runtime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.runtime.local import LocalRuntime
from cogos.db.models import Process, ProcessMode, ProcessStatus


@pytest.fixture()
def local_runtime(tmp_path: Path, monkeypatch) -> LocalRuntime:
    monkeypatch.setenv("COGTAINER", "test-local")
    monkeypatch.setenv("COGENT", "test-cogent")
    monkeypatch.setenv("USE_LOCAL_DB", "1")
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:fake")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:fake")
    monkeypatch.setenv("DB_NAME", "cogent_test")
    entry = CogtainerEntry(
        type="local", data_dir=str(tmp_path),
        llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""),
    )
    llm = MagicMock()
    rt = LocalRuntime(entry=entry, llm=llm)
    rt.create_cogent("test-cogent")
    import cogtainer.lambdas.shared.config as cfg_mod
    cfg_mod._config = None
    return rt


def test_executor_handler_gets_repo_via_runtime(local_runtime, monkeypatch):
    """Executor handler should obtain repo through the runtime, not Repository.create()."""
    from cogos.executor import handler as executor_module

    repo = local_runtime.get_repository("test-cogent")
    p = Process(
        name="test-proc", mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING, required_tags=[],
    )
    repo.upsert_process(p)

    monkeypatch.setattr(executor_module, "_get_runtime", lambda: local_runtime)
    monkeypatch.setattr(executor_module, "execute_process",
                        lambda process, event_data, run, config, repo, **kw: run)

    result = executor_module.handler(
        {"process_id": str(p.id), "run_id": None}, None,
    )

    assert result["statusCode"] == 200
