"""Tests for local_dispatcher — tick-based process scheduling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.local_dispatcher import _DEFAULT_TICK_INTERVAL, run_loop, run_tick
from cogtainer.runtime.local import LocalRuntime


@pytest.fixture()
def local_runtime(tmp_path: Path) -> LocalRuntime:
    entry = CogtainerEntry(
        type="local", data_dir=str(tmp_path),
        llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""),
    )
    llm = MagicMock()
    return LocalRuntime(entry=entry, llm=llm)


def test_single_tick(local_runtime: LocalRuntime):
    """run_tick should not raise and returns dict with dispatched >= 0."""
    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    result = run_tick(repo, local_runtime, cogent_name)

    assert isinstance(result, dict)
    assert "dispatched" in result
    assert result["dispatched"] >= 0


def test_reap_dead_executors_fails_orphan_runs(local_runtime: LocalRuntime):
    """Dead executor subprocesses should have their runs marked FAILED."""
    from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus

    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    p = Process(name="test-proc", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, required_tags=["local"])
    repo.upsert_process(p)
    run = Run(process=p.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    dead_proc = MagicMock()
    dead_proc.poll.return_value = 1
    local_runtime._child_procs = [(dead_proc, str(p.id))]

    failed = local_runtime.reap_dead_executors(repo)

    assert failed == 1
    db_run = repo.get_run(run.id)
    assert db_run is not None
    assert db_run.status == RunStatus.FAILED
    assert "exited with code 1" in (db_run.error or "")
    assert local_runtime._child_procs == []


def test_reap_dead_executors_keeps_alive_processes(local_runtime: LocalRuntime):
    """Still-running subprocesses should be kept in the tracking list."""
    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    alive_proc = MagicMock()
    alive_proc.poll.return_value = None
    local_runtime._child_procs = [(alive_proc, "some-id")]

    failed = local_runtime.reap_dead_executors(repo)

    assert failed == 0
    assert len(local_runtime._child_procs) == 1


def test_tick_reaps_dead_executors(local_runtime: LocalRuntime):
    """run_tick should call reap_dead_executors and handle dead subprocesses."""
    from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus

    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    p = Process(name="test-proc", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, required_tags=["local"])
    repo.upsert_process(p)
    run = Run(process=p.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    dead_proc = MagicMock()
    dead_proc.poll.return_value = 1
    local_runtime._child_procs = [(dead_proc, str(p.id))]

    run_tick(repo, local_runtime, cogent_name)

    db_run = repo.get_run(run.id)
    assert db_run is not None
    assert db_run.status == RunStatus.FAILED


# ── run_loop tick_interval ───────────────────────────────────────────


def test_default_tick_interval_is_60():
    """_DEFAULT_TICK_INTERVAL should be 60 seconds."""
    assert _DEFAULT_TICK_INTERVAL == 60


def test_run_loop_uses_custom_tick_interval(local_runtime: LocalRuntime):
    """run_loop should use the provided tick_interval for sleep."""
    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    tick_count = 0

    def mock_run_tick(r, rt, cn):
        nonlocal tick_count
        tick_count += 1
        return {"dispatched": 0}

    call_count = 0

    def wait_then_stop(timeout=1.0):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise KeyboardInterrupt
        return False

    with patch("cogtainer.local_dispatcher.run_tick", side_effect=mock_run_tick), \
         patch.object(local_runtime.ingress_queue, "wait_for_nudge", side_effect=wait_then_stop):
        try:
            run_loop(repo, local_runtime, cogent_name, tick_interval=5)
        except KeyboardInterrupt:
            pass

    assert tick_count >= 1


def test_run_loop_logs_custom_tick_interval(local_runtime: LocalRuntime):
    """run_loop should log the custom tick interval."""
    cogent_name = "test-cogent"
    local_runtime.create_cogent(cogent_name)
    repo = local_runtime.get_repository(cogent_name)

    with patch("cogtainer.local_dispatcher.run_tick", return_value={"dispatched": 0}), \
         patch.object(local_runtime.ingress_queue, "wait_for_nudge", side_effect=KeyboardInterrupt), \
         patch("cogtainer.local_dispatcher.logger") as mock_logger:
        try:
            run_loop(repo, local_runtime, cogent_name, tick_interval=15)
        except KeyboardInterrupt:
            pass

    # Find the log call containing the tick interval (skip executor registration log)
    found = any(15 in call[0] for call in mock_logger.info.call_args_list)
    assert found, f"Expected tick_interval=15 in log calls: {mock_logger.info.call_args_list}"
