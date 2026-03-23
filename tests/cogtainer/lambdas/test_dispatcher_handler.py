"""Tests for the dispatcher Lambda handler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.runtime.local import LocalRuntime


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
    # Reset cached config singleton between tests
    import cogtainer.lambdas.shared.config as cfg_mod
    cfg_mod._config = None
    return rt


def test_dispatcher_handler_gets_repo_via_runtime(local_runtime, monkeypatch):
    """Dispatcher handler should obtain the repo through create_executor_runtime."""
    from cogtainer.lambdas.dispatcher import handler as dispatcher_module

    monkeypatch.setattr(
        dispatcher_module, "create_executor_runtime", lambda: local_runtime,
    )
    monkeypatch.setattr(dispatcher_module.boto3, "client", MagicMock())

    result = dispatcher_module.handler({}, None)

    assert result["statusCode"] == 200
    assert "dispatched" in result


def test_dispatcher_dispatches_runnable_process(local_runtime, monkeypatch):
    """Dispatcher should find and dispatch a runnable process."""
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    from cogtainer.lambdas.dispatcher import handler as dispatcher_module

    repo = local_runtime.get_repository("test-cogent")
    p = Process(
        name="init", mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNABLE, required_tags=[], priority=100.0,
    )
    repo.upsert_process(p)

    monkeypatch.setattr(
        dispatcher_module, "create_executor_runtime", lambda: local_runtime,
    )
    mock_lambda = MagicMock()
    mock_lambda.invoke.return_value = {"StatusCode": 202}
    monkeypatch.setattr(dispatcher_module.boto3, "client", lambda *a, **kw: mock_lambda)

    result = dispatcher_module.handler({}, None)

    assert result["statusCode"] == 200
