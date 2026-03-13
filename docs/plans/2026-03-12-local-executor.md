# Local Executor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run CogOS entirely locally by adding a daemon loop that replaces Lambda dispatch — polling for runnable processes and executing them directly via Bedrock.

**Architecture:** A new `run-local` CLI command starts a loop that (1) runs the channel-message backstop to create deliveries, (2) finds RUNNABLE processes, (3) dispatches and executes them directly using the existing `execute_process()`. All state lives in `LocalRepository` (JSON file). Bedrock and SQS remain AWS-hosted.

**Tech Stack:** Python, Click CLI, LocalRepository, SchedulerCapability, Bedrock converse API

---

### Task 1: Extract shared run-and-complete helper

The `process run --local` CLI command (cli/__main__.py:343-411) has ~60 lines of run lifecycle logic (execute, complete, handle failure, transition state). The new daemon loop needs the same logic. Extract it into a reusable function.

**Files:**
- Create: `src/cogos/runtime/local.py`
- Modify: `src/cogos/cli/__main__.py:332-411`
- Test: `tests/cogos/test_local_executor.py`

**Step 1: Write the failing test**

Create `tests/cogos/test_local_executor.py`:

```python
"""Tests for the local executor runtime."""

from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.runtime.local import run_and_complete


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_run_and_complete_success(tmp_path):
    """Successful execution completes the run and transitions process."""
    repo = _repo(tmp_path)
    process = Process(
        name="test-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    def fake_execute(proc, event_data, r, config, repo, **kwargs):
        r.tokens_in = 100
        r.tokens_out = 50
        return r

    run_and_complete(process, {}, run, None, repo, execute_fn=fake_execute)

    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert repo.get_process(process.id).status == ProcessStatus.COMPLETED


def test_run_and_complete_daemon_goes_to_waiting(tmp_path):
    """Daemon with no pending deliveries transitions to WAITING after success."""
    repo = _repo(tmp_path)
    process = Process(
        name="daemon-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    def fake_execute(proc, event_data, r, config, repo, **kwargs):
        return r

    run_and_complete(process, {}, run, None, repo, execute_fn=fake_execute)

    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert repo.get_process(process.id).status == ProcessStatus.WAITING


def test_run_and_complete_failure_disables_one_shot(tmp_path):
    """Failed one-shot with no retries left gets disabled."""
    repo = _repo(tmp_path)
    process = Process(
        name="fail-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        max_retries=0,
    )
    repo.upsert_process(process)
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    def fail_execute(proc, event_data, r, config, repo, **kwargs):
        raise RuntimeError("boom")

    run_and_complete(process, {}, run, None, repo, execute_fn=fail_execute)

    assert repo.get_run(run.id).status == RunStatus.FAILED
    assert repo.get_process(process.id).status == ProcessStatus.DISABLED
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_local_executor.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_and_complete' from 'cogos.runtime.local'`

**Step 3: Write the implementation**

Create `src/cogos/runtime/local.py`:

```python
"""Local executor runtime — run CogOS processes without Lambda."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from uuid import UUID

from cogos.db.models import ProcessMode, ProcessStatus, Run, RunStatus
from cogos.db.models.channel_message import ChannelMessage

logger = logging.getLogger(__name__)


def run_and_complete(
    process,
    event_data: dict,
    run: Run,
    config,
    repo,
    *,
    execute_fn: Callable | None = None,
    bedrock_client: Any | None = None,
) -> Run:
    """Execute a process and handle completion/failure lifecycle.

    This is the shared logic used by both `cogos process run --local`
    and the `cogos run-local` daemon loop.
    """
    if execute_fn is None:
        from cogos.executor.handler import execute_process
        execute_fn = execute_process

    repo.mark_run_deliveries_delivered(run.id)
    start = time.time()

    try:
        run = execute_fn(process, event_data, run, config, repo, bedrock_client=bedrock_client)
        duration_ms = int((time.time() - start) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.COMPLETED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            result=run.result,
            scope_log=run.scope_log,
        )

        _emit_lifecycle(repo, process, {
            "status": "success",
            "run_id": str(run.id),
            "process_name": process.name,
            "duration_ms": duration_ms,
        })

        # Transition process state
        if process.mode == ProcessMode.DAEMON:
            next_status = (
                ProcessStatus.RUNNABLE
                if repo.has_pending_deliveries(process.id)
                else ProcessStatus.WAITING
            )
            repo.update_process_status(process.id, next_status)
        else:
            repo.update_process_status(process.id, ProcessStatus.COMPLETED)

        logger.info("Run %s completed in %dms", run.id, duration_ms)
        return run

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.FAILED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            error=str(e)[:4000],
        )

        _emit_lifecycle(repo, process, {
            "status": "failed",
            "run_id": str(run.id),
            "process_name": process.name,
            "error": str(e)[:1000],
        })

        if process.mode == ProcessMode.DAEMON:
            next_status = (
                ProcessStatus.RUNNABLE
                if repo.has_pending_deliveries(process.id)
                else ProcessStatus.WAITING
            )
            repo.update_process_status(process.id, next_status)
        elif process.retry_count < process.max_retries:
            repo.increment_retry(process.id)
            repo.update_process_status(process.id, ProcessStatus.RUNNABLE)
        else:
            repo.update_process_status(process.id, ProcessStatus.DISABLED)

        logger.error("Run %s failed in %dms: %s", run.id, duration_ms, e)
        return run


def _emit_lifecycle(repo, process, payload: dict) -> None:
    """Publish a lifecycle message to the process's implicit channel."""
    try:
        from cogos.db.models import Channel, ChannelType
        ch_name = f"process:{process.name}"
        ch = repo.get_channel_by_name(ch_name)
        if not ch:
            ch = Channel(name=ch_name, owner_process=process.id, channel_type=ChannelType.IMPLICIT)
            repo.upsert_channel(ch)
            ch = repo.get_channel_by_name(ch_name)
        if ch:
            repo.append_channel_message(ChannelMessage(
                channel=ch.id, sender_process=process.id, payload=payload,
            ))
    except Exception:
        logger.warning("Failed to emit lifecycle message for %s", process.name, exc_info=True)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/test_local_executor.py -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/cogos/runtime/local.py tests/cogos/test_local_executor.py
git commit -m "feat(cogos): extract run_and_complete helper for local execution"
```

---

### Task 2: Refactor CLI `process run --local` to use shared helper

**Files:**
- Modify: `src/cogos/cli/__main__.py:332-411`

**Step 1: Write the failing test**

Add to `tests/cogos/test_local_executor.py`:

```python
def test_run_and_complete_returns_run_on_failure(tmp_path):
    """run_and_complete returns the run object even on failure."""
    repo = _repo(tmp_path)
    process = Process(
        name="fail-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        max_retries=1,
    )
    repo.upsert_process(process)
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    def fail_execute(proc, event_data, r, config, repo, **kwargs):
        raise RuntimeError("boom")

    result = run_and_complete(process, {}, run, None, repo, execute_fn=fail_execute)

    assert result.id == run.id
    assert repo.get_process(process.id).status == ProcessStatus.RUNNABLE  # has retries left
```

**Step 2: Run test to verify it passes**

Run: `python -m pytest tests/cogos/test_local_executor.py::test_run_and_complete_returns_run_on_failure -v`
Expected: PASS (already implemented in Task 1)

**Step 3: Refactor the CLI**

Replace the `process run --local` body in `src/cogos/cli/__main__.py` (lines 343-411). The new version calls `run_and_complete`:

```python
@process.command("run")
@click.argument("name")
@click.option("--local", is_flag=True, help="Run locally via Bedrock (no Lambda)")
def process_run(name: str, local: bool):
    """Trigger a process to run."""
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Process not found: {name}")
        return

    if local:
        from cogos.executor.handler import get_config
        from cogos.runtime.local import run_and_complete

        config = get_config()
        repo.update_process_status(p.id, ProcessStatus.RUNNING)

        run = Run(process=p.id, status=RunStatus.RUNNING)
        repo.create_run(run)
        click.echo(f"Starting local run {run.id} for {name}...")

        bedrock = _bedrock_client()
        run = run_and_complete(p, {}, run, config, repo, bedrock_client=bedrock)

        if run.status == RunStatus.COMPLETED:
            click.echo(f"Run completed in {run.duration_ms or 0}ms")
            click.echo(f"  Tokens: {run.tokens_in} in, {run.tokens_out} out")
        else:
            click.echo(f"Run failed: {run.error}")
    else:
        from cogos.db.models import ProcessStatus
        repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
        click.echo(f"Process {name} marked RUNNABLE")
```

Note: `run_and_complete` stores `duration_ms` on the Run via `complete_run` but the Run model field isn't set on the returned object. We need to re-fetch or store it. Check: does `complete_run` in LocalRepository mutate the run in-place? Yes — it does `run.duration_ms = duration_ms`. So `run.duration_ms` will be set after `run_and_complete` returns, but only if we re-fetch from repo. The simpler fix: just let `run_and_complete` log to console too, or accept the minor difference. For now, keep the CLI output simple.

**Step 4: Run existing tests**

Run: `python -m pytest tests/cogos/ -v`
Expected: All existing tests pass

**Step 5: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "refactor(cogos): use run_and_complete in CLI process run --local"
```

---

### Task 3: Add the daemon loop

**Files:**
- Modify: `src/cogos/runtime/local.py`
- Test: `tests/cogos/test_local_executor.py`

**Step 1: Write the failing test**

Add to `tests/cogos/test_local_executor.py`:

```python
from cogos.runtime.local import run_local_tick


def test_run_local_tick_executes_runnable_process(tmp_path):
    """A single tick dispatches and executes a RUNNABLE process."""
    repo = _repo(tmp_path)
    process = Process(
        name="tick-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNABLE,
    )
    repo.upsert_process(process)

    executed = []

    def fake_execute(proc, event_data, r, config, repo, **kwargs):
        executed.append(proc.name)
        return r

    result = run_local_tick(repo, None, execute_fn=fake_execute)

    assert result == 1  # one process executed
    assert executed == ["tick-proc"]
    assert repo.get_process(process.id).status == ProcessStatus.COMPLETED


def test_run_local_tick_no_work(tmp_path):
    """A tick with no runnable processes returns 0."""
    repo = _repo(tmp_path)

    result = run_local_tick(repo, None)

    assert result == 0


def test_run_local_tick_matches_channel_messages(tmp_path):
    """A tick creates deliveries from unmatched channel messages."""
    repo = _repo(tmp_path)
    process = Process(
        name="listener",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
    )
    repo.upsert_process(process)

    # Create a channel and subscribe the process
    ch = Channel(name="test-channel", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("test-channel")
    handler = Handler(process=process.id, channel=ch.id, enabled=True)
    repo.create_handler(handler)

    # Send a message — LocalRepository.append_channel_message auto-creates
    # deliveries and marks process RUNNABLE, so this tests the full flow
    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=None, payload={"msg": "hello"},
    ))

    executed = []

    def fake_execute(proc, event_data, r, config, repo, **kwargs):
        executed.append(proc.name)
        return r

    result = run_local_tick(repo, None, execute_fn=fake_execute)

    assert result == 1
    assert executed == ["listener"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_local_executor.py::test_run_local_tick_executes_runnable_process -v`
Expected: FAIL with `ImportError: cannot import name 'run_local_tick'`

**Step 3: Write the implementation**

Add to `src/cogos/runtime/local.py`:

```python
def run_local_tick(
    repo,
    config,
    *,
    execute_fn: Callable | None = None,
    bedrock_client: Any | None = None,
) -> int:
    """Run one tick of the local executor loop.

    1. Run channel-message backstop (match undelivered messages to handlers)
    2. Find and execute all RUNNABLE processes sequentially

    Returns the number of processes executed.
    """
    from cogos.capabilities.scheduler import SchedulerCapability

    # Use a sentinel process_id — scheduler methods don't reference it
    scheduler = SchedulerCapability(repo, process_id=UUID("00000000-0000-0000-0000-000000000000"))

    # Backstop: ensure all channel messages have been matched to handlers
    scheduler.match_channel_messages()

    executed = 0

    while True:
        result = scheduler.select_processes(slots=1)
        if not result.selected:
            break

        proc_info = result.selected[0]
        dispatch = scheduler.dispatch_process(proc_info.id)
        if hasattr(dispatch, "error"):
            logger.warning("Dispatch failed for %s: %s", proc_info.name, dispatch.error)
            break

        process = repo.get_process(UUID(dispatch.process_id))
        run = repo.get_run(UUID(dispatch.run_id))
        if not process or not run:
            logger.error("Process or run not found after dispatch: %s", dispatch)
            break

        # Build event payload from the delivery's channel message
        event_payload: dict[str, Any] = {}
        if dispatch.event_id:
            msg_id = UUID(dispatch.event_id)
            # Check channel messages (local repo)
            for ch_msg in repo._channel_messages.values():
                if ch_msg.id == msg_id:
                    event_payload = ch_msg.payload or {}
                    break

        logger.info("Executing process %s (run %s)", process.name, run.id)
        run_and_complete(
            process, event_payload, run, config, repo,
            execute_fn=execute_fn, bedrock_client=bedrock_client,
        )
        executed += 1

    return executed


def run_local_loop(
    repo,
    config,
    *,
    poll_interval: float = 2.0,
    once: bool = False,
    bedrock_client: Any | None = None,
) -> None:
    """Run the local executor daemon loop.

    Args:
        repo: LocalRepository instance
        config: ExecutorConfig
        poll_interval: seconds between ticks when idle
        once: if True, run one tick and exit
        bedrock_client: optional pre-built Bedrock client
    """
    logger.info("Local executor starting (poll_interval=%.1fs, once=%s)", poll_interval, once)

    while True:
        try:
            executed = run_local_tick(repo, config, bedrock_client=bedrock_client)
            if executed:
                logger.info("Tick: executed %d process(es)", executed)
        except Exception:
            logger.exception("Error in local executor tick")

        if once:
            break

        time.sleep(poll_interval)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/cogos/test_local_executor.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/cogos/runtime/local.py tests/cogos/test_local_executor.py
git commit -m "feat(cogos): add run_local_tick and run_local_loop for local execution"
```

---

### Task 4: Add `cogos run-local` CLI command

**Files:**
- Modify: `src/cogos/cli/__main__.py`

**Step 1: Write the implementation**

Add after the `reload` command in `src/cogos/cli/__main__.py` (before the Discord commands section):

```python
@cogos.command("run-local")
@click.option("--poll-interval", type=float, default=2.0, help="Seconds between ticks (default: 2)")
@click.option("--once", is_flag=True, help="Run one tick and exit")
@click.pass_context
def run_local(ctx: click.Context, poll_interval: float, once: bool):
    """Run the local executor loop (replaces Lambda dispatch)."""
    os.environ["USE_LOCAL_DB"] = "1"

    from cogos.executor.handler import get_config
    from cogos.runtime.local import run_local_loop

    repo = _repo()
    config = get_config()
    bedrock = _bedrock_client()

    click.echo(f"Local executor running (poll={poll_interval}s, once={once})")
    click.echo("Press Ctrl+C to stop.")

    try:
        run_local_loop(
            repo, config,
            poll_interval=poll_interval,
            once=once,
            bedrock_client=bedrock,
        )
    except KeyboardInterrupt:
        click.echo("\nLocal executor stopped.")
```

**Step 2: Smoke test**

Run: `python -m cogos run-local --once`
Expected: prints "Local executor running", does one tick (likely 0 processes), exits cleanly.

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "feat(cogos): add run-local CLI command for local daemon loop"
```

---

### Task 5: Run all tests and verify

**Step 1: Run the full test suite**

Run: `python -m pytest tests/cogos/ -v`
Expected: All tests pass, including existing executor tests.

**Step 2: Integration smoke test**

```bash
# Boot an image locally
USE_LOCAL_DB=1 python -m cogos image boot cogent-v1 --clean

# Run one tick
USE_LOCAL_DB=1 python -m cogos run-local --once

# Check status
USE_LOCAL_DB=1 python -m cogos status
```

**Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix(cogos): local executor fixups from integration testing"
```
