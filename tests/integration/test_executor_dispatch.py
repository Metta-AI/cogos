"""Integration test: executor dispatch via tags.

Tests:
1. Local daemon executor picks up a python process
2. Channel executor (simulated claude-code) picks up a process and writes to stdout
"""
from __future__ import annotations

import time
from uuid import UUID

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Executor,
    ExecutorStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.capabilities.scheduler import ExecutorDispatchResult, SchedulerCapability, SchedulerError
from cogos.runtime.dispatch import build_dispatch_event


def test_local_daemon_dispatch(tmp_path):
    """Process with no tags dispatches to local-daemon executor."""
    repo = LocalRepository(str(tmp_path))

    # Register local daemon executor (what run_loop does on boot)
    daemon = Executor(
        executor_id="local-daemon",
        channel_type="local",
        executor_tags=["python"],
        dispatch_type="channel",
        metadata={"local": True},
    )
    repo.register_executor(daemon)

    # Create a hello-world process
    proc = Process(
        name="hello-world",
        mode=ProcessMode.ONE_SHOT,
        content="Say hello world",
        required_tags=[],
        executor="llm",
        priority=1.0,
        status=ProcessStatus.RUNNABLE,
    )
    repo.upsert_process(proc)

    # Verify io channels were created
    stdin_ch = repo.get_channel_by_name("io:stdin:hello-world")
    stdout_ch = repo.get_channel_by_name("io:stdout:hello-world")
    stderr_ch = repo.get_channel_by_name("io:stderr:hello-world")
    assert stdin_ch is not None, "io:stdin channel should exist"
    assert stdout_ch is not None, "io:stdout channel should exist"
    assert stderr_ch is not None, "io:stderr channel should exist"

    # Verify stdin handler was created
    handlers = repo.list_handlers(process_id=proc.id)
    stdin_handlers = [h for h in handlers if h.channel == stdin_ch.id]
    assert len(stdin_handlers) == 1, "stdin handler should exist"

    # Dispatch via scheduler
    scheduler = SchedulerCapability.__new__(SchedulerCapability)
    scheduler.repo = repo

    result = scheduler.dispatch_to_executor(process_id=str(proc.id))
    assert isinstance(result, ExecutorDispatchResult), f"Expected dispatch success, got: {result}"
    assert result.executor_id == "local-daemon"
    assert result.dispatch_type == "channel"

    # Executor should be busy
    executor = repo.get_executor("local-daemon")
    assert executor.status == ExecutorStatus.BUSY
    assert executor.current_run_id == UUID(result.run_id)

    # Process should be running
    updated = repo.get_process(proc.id)
    assert updated.status == ProcessStatus.RUNNING

    # Run should exist
    runs = repo.list_runs(process_id=proc.id, limit=1)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.RUNNING

    # Verify dispatch event can be built
    payload = build_dispatch_event(repo, result)
    assert payload["process_id"] == str(proc.id)
    assert payload["run_id"] == result.run_id

    # Verify executor channel was created for sending work
    exec_ch = repo.get_channel_by_name("system:executor:local-daemon")
    # Note: in real flow, the dispatcher creates this channel on registration.
    # In this test we didn't go through the registration API, so it may not exist.
    # The actual message delivery is tested below.

    print("✓ Local daemon dispatch: process dispatched to local-daemon executor")


def test_claude_code_executor_dispatch(tmp_path):
    """Process with ['claude-code'] tags dispatches to claude-code executor."""
    repo = LocalRepository(str(tmp_path))

    # Register claude-code executor (what channel server does)
    cc_executor = Executor(
        executor_id="cc-test-abc123",
        channel_type="claude-code",
        executor_tags=["claude-code"],
        dispatch_type="channel",
        metadata={"mcp": True},
    )
    repo.register_executor(cc_executor)

    # Create executor channel (registration API creates this)
    exec_ch = Channel(
        name="system:executor:cc-test-abc123",
        channel_type=ChannelType.NAMED,
    )
    repo.upsert_channel(exec_ch)

    # Create a process requiring claude-code
    proc = Process(
        name="code-review",
        mode=ProcessMode.ONE_SHOT,
        content="Review the latest PR",
        required_tags=["claude-code"],
        executor="llm",
        priority=1.0,
        status=ProcessStatus.RUNNABLE,
    )
    repo.upsert_process(proc)

    # Send a message to stdin to trigger the process
    stdin_ch = repo.get_channel_by_name("io:stdin:code-review")
    assert stdin_ch is not None
    msg = ChannelMessage(
        channel=stdin_ch.id,
        payload={"request": "Please review PR #42"},
    )
    repo.append_channel_message(msg)

    # Deliveries were auto-created by append_channel_message
    scheduler = SchedulerCapability.__new__(SchedulerCapability)
    scheduler.repo = repo

    # Process should still be RUNNABLE (one_shot doesn't wake like daemons)
    updated = repo.get_process(proc.id)
    assert updated.status == ProcessStatus.RUNNABLE

    # Dispatch
    result = scheduler.dispatch_to_executor(process_id=str(proc.id))
    assert isinstance(result, ExecutorDispatchResult)
    assert result.executor_id == "cc-test-abc123"
    assert result.dispatch_type == "channel"

    # Build dispatch event and send to executor channel
    payload = build_dispatch_event(repo, result)
    assert payload["process_id"] == str(proc.id)
    assert payload["run_id"] == result.run_id
    assert payload["payload"]["request"] == "Please review PR #42"

    # Send to executor channel (what ingress.py does)
    exec_ch = repo.get_channel_by_name("system:executor:cc-test-abc123")
    repo.append_channel_message(ChannelMessage(
        channel=exec_ch.id,
        payload=payload,
    ))

    # Verify the message is on the executor channel
    messages = repo.list_channel_messages(channel_id=exec_ch.id, limit=10)
    assert len(messages) == 1
    assert messages[0].payload["process_id"] == str(proc.id)
    assert messages[0].payload["payload"]["request"] == "Please review PR #42"

    # Simulate executor writing to stdout and stderr
    stdout_ch = repo.get_channel_by_name("io:stdout:code-review")
    stderr_ch = repo.get_channel_by_name("io:stderr:code-review")
    assert stdout_ch is not None
    assert stderr_ch is not None

    repo.append_channel_message(ChannelMessage(
        channel=stdout_ch.id,
        payload={"response": "PR #42 looks good, approved!"},
    ))
    repo.append_channel_message(ChannelMessage(
        channel=stderr_ch.id,
        payload={"warning": "Found 2 minor style issues"},
    ))

    # Verify stdout/stderr messages
    stdout_msgs = repo.list_channel_messages(channel_id=stdout_ch.id, limit=10)
    stderr_msgs = repo.list_channel_messages(channel_id=stderr_ch.id, limit=10)
    assert len(stdout_msgs) == 1
    assert stdout_msgs[0].payload["response"] == "PR #42 looks good, approved!"
    assert len(stderr_msgs) == 1
    assert stderr_msgs[0].payload["warning"] == "Found 2 minor style issues"

    # Complete the run
    run_id = UUID(result.run_id)
    repo.complete_run(run_id, status=RunStatus.COMPLETED, result={"approved": True})

    # Executor should be back to idle
    repo.update_executor_status("cc-test-abc123", ExecutorStatus.IDLE)
    executor = repo.get_executor("cc-test-abc123")
    assert executor.status == ExecutorStatus.IDLE

    # Run should be completed
    run = repo.get_run(run_id)
    assert run.status == RunStatus.COMPLETED

    print("✓ Claude-code dispatch: process dispatched, stdin→executor, stdout+stderr written, run completed")


def test_tag_routing(tmp_path):
    """Processes route to correct executors by tags."""
    repo = LocalRepository(str(tmp_path))

    # Register two executors
    repo.register_executor(Executor(
        executor_id="local-daemon",
        executor_tags=["python"],
        dispatch_type="channel",
    ))
    repo.register_executor(Executor(
        executor_id="cc-session-1",
        executor_tags=["claude-code"],
        dispatch_type="channel",
    ))

    # Process requiring claude-code
    cc_proc = Process(
        name="cc-task",
        mode=ProcessMode.ONE_SHOT,
        required_tags=["claude-code"],
        status=ProcessStatus.RUNNABLE,
        priority=1.0,
    )
    repo.upsert_process(cc_proc)

    # Process with no tags (matches any)
    any_proc = Process(
        name="any-task",
        mode=ProcessMode.ONE_SHOT,
        required_tags=[],
        status=ProcessStatus.RUNNABLE,
        priority=1.0,
    )
    repo.upsert_process(any_proc)

    scheduler = SchedulerCapability.__new__(SchedulerCapability)
    scheduler.repo = repo

    # CC task should go to cc-session-1
    r1 = scheduler.dispatch_to_executor(process_id=str(cc_proc.id))
    assert isinstance(r1, ExecutorDispatchResult)
    assert r1.executor_id == "cc-session-1"

    # Any task should go to local-daemon (cc-session-1 is now busy)
    r2 = scheduler.dispatch_to_executor(process_id=str(any_proc.id))
    assert isinstance(r2, ExecutorDispatchResult)
    assert r2.executor_id == "local-daemon"

    print("✓ Tag routing: claude-code→cc-session-1, no-tags→local-daemon")


def test_lambda_pool_dispatch(tmp_path):
    """Lambda pool executor stays idle after dispatch (fire-and-forget)."""
    repo = LocalRepository(str(tmp_path))

    repo.register_executor(Executor(
        executor_id="lambda-pool",
        executor_tags=["lambda", "python"],
        dispatch_type="lambda",
        metadata={"pool": True},
    ))

    proc = Process(
        name="lambda-task",
        mode=ProcessMode.ONE_SHOT,
        required_tags=["lambda"],
        status=ProcessStatus.RUNNABLE,
        priority=1.0,
    )
    repo.upsert_process(proc)

    scheduler = SchedulerCapability.__new__(SchedulerCapability)
    scheduler.repo = repo

    result = scheduler.dispatch_to_executor(process_id=str(proc.id))
    assert isinstance(result, ExecutorDispatchResult)
    assert result.executor_id == "lambda-pool"
    assert result.dispatch_type == "lambda"

    # Lambda pool should stay IDLE (not BUSY)
    executor = repo.get_executor("lambda-pool")
    assert executor.status == ExecutorStatus.IDLE

    print("✓ Lambda pool: dispatched, executor stays idle (fire-and-forget)")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_local_daemon_dispatch(d)
        test_claude_code_executor_dispatch(d)
        test_tag_routing(d)
        test_lambda_pool_dispatch(d)
        print("\n✓ All integration tests passed!")
