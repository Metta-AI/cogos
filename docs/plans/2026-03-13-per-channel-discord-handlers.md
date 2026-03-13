# Per-Channel Discord Sub-Handlers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Discord messages are routed to per-channel child processes so the parent handler only wakes for new/unrecognized channels.

**Architecture:** The bridge writes each message to both a fine-grained channel (`io:discord:message:<discord_channel_id>`) and the catch-all (`io:discord:message`). The parent handler checks if a child process already exists for that Discord channel — if yes, it returns immediately (child already got the delivery on the fine-grained channel). If no, it spawns a daemon child subscribed to the fine-grained channel. An idle timeout on daemon processes lets the scheduler reap children that haven't received messages in a while.

**Tech Stack:** Python, Pydantic models, LocalRepository + RDS Repository, pytest

---

### Task 1: Add `subscribe` param to `procs.spawn()`

Allow spawn to create a Handler binding the child to an existing named channel.

**Files:**
- Modify: `src/cogos/capabilities/procs.py` (the `spawn` method)
- Test: `tests/cogos/capabilities/test_spawn_subscribe.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_spawn_subscribe.py`:

```python
"""Tests for spawn() subscribe parameter — binds child to a channel handler."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.procs import ProcsCapability, ProcessError
from cogos.db.models import Channel, ChannelType


def _make_cap_model(name="files"):
    m = MagicMock()
    m.id = uuid4()
    m.enabled = True
    m.name = name
    return m


def test_spawn_with_subscribe_creates_handler():
    """spawn(subscribe="ch-name") should create a Handler binding child to that channel."""
    repo = MagicMock()
    parent_pid = uuid4()
    child_id = uuid4()
    repo.upsert_process.return_value = child_id

    ch = Channel(name="io:discord:message:12345", channel_type=ChannelType.NAMED)
    repo.get_channel_by_name.return_value = ch
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work", subscribe="io:discord:message:12345")

    assert not isinstance(result, ProcessError)
    repo.create_handler.assert_called_once()
    handler = repo.create_handler.call_args.args[0]
    assert handler.process == child_id
    assert handler.channel == ch.id


def test_spawn_with_subscribe_channel_not_found():
    """spawn(subscribe="missing") should return error if channel doesn't exist."""
    repo = MagicMock()
    parent_pid = uuid4()
    repo.upsert_process.return_value = uuid4()
    repo.get_channel_by_name.return_value = None
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work", subscribe="no-such-channel")

    assert isinstance(result, ProcessError)
    assert "not found" in result.error.lower()


def test_spawn_without_subscribe_no_handler():
    """spawn() without subscribe should NOT create a handler (existing behavior)."""
    repo = MagicMock()
    parent_pid = uuid4()
    repo.upsert_process.return_value = uuid4()
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work")

    assert not isinstance(result, ProcessError)
    repo.create_handler.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_spawn_subscribe.py -v`
Expected: FAIL — `spawn()` doesn't accept `subscribe` param yet

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/procs.py`, modify the `spawn` method:

1. Add `subscribe: str | None = None` parameter
2. After creating spawn channels, if `subscribe` is set:
   - Look up the channel by name via `self.repo.get_channel_by_name(subscribe)`
   - If not found, return `ProcessError(error=f"Subscribe channel '{subscribe}' not found")`
   - Create a `Handler(process=child_id, channel=ch.id)` via `self.repo.create_handler(handler)`

```python
def spawn(
    self,
    name: str,
    content: str = "",
    code: str | None = None,
    priority: float = 0.0,
    runner: str = "lambda",
    model: str | None = None,
    capabilities: dict[str, "Capability | None"] | None = None,
    schema: dict | None = None,
    subscribe: str | None = None,
) -> ProcessHandle | ProcessError:
```

Add after the spawn channel creation block (after `self.repo.upsert_channel(recv_ch)`):

```python
        # Bind child to a channel handler if subscribe is set
        if subscribe:
            from cogos.db.models import Handler

            sub_ch = self.repo.get_channel_by_name(subscribe)
            if sub_ch is None:
                return ProcessError(error=f"Subscribe channel '{subscribe}' not found")
            self.repo.create_handler(Handler(process=child_id, channel=sub_ch.id))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_spawn_subscribe.py -v`
Expected: PASS

**Step 5: Run existing spawn tests to verify no regression**

Run: `pytest tests/cogos/capabilities/test_spawn_delegation.py tests/cogos/capabilities/test_spawn_scoped.py tests/cogos/capabilities/test_procs_scoping.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/cogos/capabilities/test_spawn_subscribe.py src/cogos/capabilities/procs.py
git commit -m "feat(procs): add subscribe param to spawn() for channel handler binding"
```

---

### Task 2: Bridge writes to fine-grained per-channel channels

Update the bridge to write each message to both the catch-all and a per-Discord-channel channel.

**Files:**
- Modify: `src/cogos/io/discord/bridge.py` (`_relay_to_db` method)
- Test: `tests/io/test_discord_bridge.py` (add new tests)

**Step 1: Write the failing tests**

Add to `tests/io/test_discord_bridge.py` in the `TestBridgeInbound` class:

```python
    async def test_relay_channel_message_writes_to_fine_grained_channel(self):
        """Channel messages should also write to io:discord:message:<channel_id>."""
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        catch_all = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
        fine = Channel(name="io:discord:message:100", channel_type=ChannelType.NAMED)

        def _get_channel(name):
            if name == "io:discord:message":
                return catch_all
            if name == "io:discord:message:100":
                return fine
            return None

        repo.get_channel_by_name.side_effect = _get_channel

        msg = _make_message(content="hi", channel_id=100)
        await bridge._relay_to_db(msg)

        assert repo.append_channel_message.call_count == 2
        channels_written = {call.args[0].channel for call in repo.append_channel_message.call_args_list}
        assert catch_all.id in channels_written
        assert fine.id in channels_written

    async def test_relay_dm_writes_to_fine_grained_channel(self):
        """DM messages should also write to io:discord:dm:<author_id>."""
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        catch_all = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
        fine = Channel(name="io:discord:dm:42", channel_type=ChannelType.NAMED)

        def _get_channel(name):
            if name == "io:discord:dm":
                return catch_all
            if name == "io:discord:dm:42":
                return fine
            return None

        repo.get_channel_by_name.side_effect = _get_channel

        msg = _make_message(is_dm=True, content="secret")
        await bridge._relay_to_db(msg)

        assert repo.append_channel_message.call_count == 2
        channels_written = {call.args[0].channel for call in repo.append_channel_message.call_args_list}
        assert catch_all.id in channels_written
        assert fine.id in channels_written

    async def test_relay_creates_fine_grained_channel_if_missing(self):
        """Fine-grained channel should be auto-created if it doesn't exist."""
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        catch_all = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
        created_fine = Channel(name="io:discord:message:100", channel_type=ChannelType.NAMED)

        call_count = {"fine": 0}

        def _get_channel(name):
            if name == "io:discord:message":
                return catch_all
            if name == "io:discord:message:100":
                call_count["fine"] += 1
                # First call: doesn't exist. Second call (after upsert): exists.
                return None if call_count["fine"] == 1 else created_fine
            return None

        repo.get_channel_by_name.side_effect = _get_channel

        msg = _make_message(content="hi", channel_id=100)
        await bridge._relay_to_db(msg)

        # Should have upserted the fine-grained channel
        upsert_calls = [c for c in repo.upsert_channel.call_args_list
                        if c.args[0].name == "io:discord:message:100"]
        assert len(upsert_calls) == 1
        assert repo.append_channel_message.call_count == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/io/test_discord_bridge.py::TestBridgeInbound::test_relay_channel_message_writes_to_fine_grained_channel tests/io/test_discord_bridge.py::TestBridgeInbound::test_relay_dm_writes_to_fine_grained_channel tests/io/test_discord_bridge.py::TestBridgeInbound::test_relay_creates_fine_grained_channel_if_missing -v`
Expected: FAIL — bridge only writes to one channel today

**Step 3: Write minimal implementation**

Refactor `_relay_to_db` in `src/cogos/io/discord/bridge.py`. After writing to the catch-all channel, also write to the fine-grained channel.

The fine-grained channel name is:
- For `discord:message`: `io:discord:message:<channel_id>`
- For `discord:dm`: `io:discord:dm:<author_id>`
- For `discord:mention`: no fine-grained channel (keep existing behavior)

Extract a helper `_get_or_create_channel(self, name)` to reduce duplication:

```python
    def _get_or_create_channel(self, repo, channel_name: str):
        """Look up a channel by name, creating it if missing."""
        ch = repo.get_channel_by_name(channel_name)
        if ch is None:
            from cogos.db.models import Channel, ChannelType
            logger.info("Creating channel %s", channel_name)
            ch = Channel(name=channel_name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(ch)
            ch = repo.get_channel_by_name(channel_name)
        return ch
```

Then in `_relay_to_db`, after writing to the catch-all channel:

```python
        # Write to fine-grained per-source channel for message and dm types
        fine_channel_name = None
        if message_type == "discord:message":
            fine_channel_name = f"io:discord:message:{payload['channel_id']}"
        elif message_type == "discord:dm":
            fine_channel_name = f"io:discord:dm:{payload['author_id']}"

        if fine_channel_name:
            fine_ch = self._get_or_create_channel(repo, fine_channel_name)
            if fine_ch:
                repo.append_channel_message(ChannelMessage(
                    channel=fine_ch.id,
                    sender_process=None,
                    payload=payload,
                ))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/io/test_discord_bridge.py -v`
Expected: PASS (all existing + new tests)

**Step 5: Run the cogos bridge tests too**

Run: `pytest tests/cogos/io/test_discord_bridge.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/io/discord/bridge.py tests/io/test_discord_bridge.py
git commit -m "feat(bridge): write discord messages to per-channel fine-grained channels"
```

---

### Task 3: Add `idle_timeout_ms` to Process model

**Files:**
- Modify: `src/cogos/db/models/process.py`
- Test: verify model instantiation

**Step 1: Write a quick model test**

Add to a new file `tests/cogos/db/test_process_idle_timeout.py`:

```python
"""Test that Process model accepts idle_timeout_ms."""
from cogos.db.models import Process, ProcessMode


def test_process_idle_timeout_default_none():
    p = Process(name="test", mode=ProcessMode.DAEMON)
    assert p.idle_timeout_ms is None


def test_process_idle_timeout_set():
    p = Process(name="test", mode=ProcessMode.DAEMON, idle_timeout_ms=300_000)
    assert p.idle_timeout_ms == 300_000
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/db/test_process_idle_timeout.py -v`
Expected: FAIL — `idle_timeout_ms` not a field on Process

**Step 3: Add the field**

In `src/cogos/db/models/process.py`, add to the `Process` class:

```python
    idle_timeout_ms: int | None = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/db/test_process_idle_timeout.py -v`
Expected: PASS

**Step 5: Add DB column for RDS repository**

Check if there's a migrations file or if schema is applied inline. If the RDS repository uses a schema file, add the column there. If schema is managed via `CREATE TABLE` statements in the repo, add `idle_timeout_ms BIGINT` to the `cogos_process` table definition.

Search for: `grep -r "cogos_process" src/cogos/db/` to find the schema definition and add the column.

Also update `src/cogos/db/repository.py` — the `upsert_process` and `get_process` methods need to read/write the new column.

**Step 6: Commit**

```bash
git add src/cogos/db/models/process.py tests/cogos/db/test_process_idle_timeout.py src/cogos/db/repository.py src/cogos/db/local_repository.py
git commit -m "feat(process): add idle_timeout_ms field to Process model"
```

---

### Task 4: Scheduler reaps idle daemon processes

Add logic to the scheduler to transition idle daemon processes to COMPLETED.

**Files:**
- Modify: `src/cogos/capabilities/scheduler.py`
- Test: `tests/cogos/test_scheduler_idle_timeout.py`

**Step 1: Write the failing test**

Create `tests/cogos/test_scheduler_idle_timeout.py`:

```python
"""Tests for scheduler idle timeout reaping."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_reap_idle_daemon(tmp_path):
    """Daemon with idle_timeout_ms whose last run completed long ago gets reaped."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="idle-child",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
        idle_timeout_ms=60_000,  # 1 minute
    )
    repo.upsert_process(proc)

    # Create a completed run from 2 minutes ago
    run = Run(
        process=proc.id,
        status=RunStatus.COMPLETED,
    )
    run_id = repo.create_run(run)
    repo.complete_run(
        run_id,
        status=RunStatus.COMPLETED,
        duration_ms=100,
    )

    # Backdate the run's created_at to 2 minutes ago
    r = repo.get_run(run_id)
    r.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    # Force update in local repo
    repo._runs[run_id] = r

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 1
    assert repo.get_process(proc.id).status == ProcessStatus.COMPLETED


def test_no_reap_active_daemon(tmp_path):
    """Daemon with recent activity should NOT be reaped."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="active-child",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
        idle_timeout_ms=300_000,  # 5 minutes
    )
    repo.upsert_process(proc)

    # Recent run — should not be reaped
    run = Run(process=proc.id, status=RunStatus.COMPLETED)
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.COMPLETED, duration_ms=100)

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 0
    assert repo.get_process(proc.id).status == ProcessStatus.WAITING


def test_no_reap_without_idle_timeout(tmp_path):
    """Daemon without idle_timeout_ms should never be reaped."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="permanent",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(proc)

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cogos/test_scheduler_idle_timeout.py -v`
Expected: FAIL — `reap_idle_processes` doesn't exist

**Step 3: Implement `reap_idle_processes`**

Add to `src/cogos/capabilities/scheduler.py`:

```python
class ReapResult(BaseModel):
    reaped_count: int = 0
    reaped: list[UnblockInfo] = []
```

Add method to `SchedulerCapability`:

```python
    def reap_idle_processes(self) -> ReapResult:
        """Reap daemon processes that have been idle longer than their idle_timeout_ms."""
        import time

        now_ts = time.time()
        daemons = self.repo.list_processes(status=ProcessStatus.WAITING)
        reaped = []

        for proc in daemons:
            if proc.mode.value != "daemon":
                continue
            if proc.idle_timeout_ms is None:
                continue

            # Find most recent completed run
            runs = self.repo.list_runs(process_id=proc.id, limit=1)
            if not runs:
                # Never ran — check created_at instead
                if proc.created_at:
                    idle_ms = (now_ts - proc.created_at.timestamp()) * 1000
                    if idle_ms > proc.idle_timeout_ms:
                        self.repo.update_process_status(proc.id, ProcessStatus.COMPLETED)
                        reaped.append(UnblockInfo(id=str(proc.id), name=proc.name))
                continue

            last_run = runs[0]
            if last_run.created_at:
                idle_ms = (now_ts - last_run.created_at.timestamp()) * 1000
                if idle_ms > proc.idle_timeout_ms:
                    self.repo.update_process_status(proc.id, ProcessStatus.COMPLETED)
                    reaped.append(UnblockInfo(id=str(proc.id), name=proc.name))

        return ReapResult(reaped_count=len(reaped), reaped=reaped)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cogos/test_scheduler_idle_timeout.py -v`
Expected: PASS

**Step 5: Run existing scheduler tests**

Run: `pytest tests/cogos/test_scheduler_channels.py tests/cogos/test_scheduler_ingress.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/scheduler.py tests/cogos/test_scheduler_idle_timeout.py
git commit -m "feat(scheduler): add reap_idle_processes for idle daemon timeout"
```

---

### Task 5: Wire idle reaping into the local executor tick

**Files:**
- Modify: `src/cogos/runtime/local.py` (`run_local_tick`)
- Modify: `src/cogtainer/lambdas/orchestrator/handler.py` (`_cogos_scheduler_tick`)

**Step 1: Add reap call to local tick**

In `src/cogos/runtime/local.py`, in `run_local_tick`, add after `scheduler.match_messages()`:

```python
    # Reap idle daemon processes
    scheduler.reap_idle_processes()
```

**Step 2: Add reap call to orchestrator tick**

In `src/cogtainer/lambdas/orchestrator/handler.py`, in `_cogos_scheduler_tick`, add after `scheduler.match_messages()`:

```python
        # Reap idle daemon processes
        scheduler.reap_idle_processes()
```

**Step 3: Run local executor tests**

Run: `pytest tests/cogos/test_local_executor.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/runtime/local.py src/cogtainer/lambdas/orchestrator/handler.py
git commit -m "feat(runtime): wire idle reaping into scheduler tick"
```

---

### Task 6: Integration test — full flow with LocalRepository

End-to-end test: bridge writes to both channels, parent handler spawns child, child receives subsequent messages, parent doesn't invoke executor for handled channels.

**Files:**
- Test: `tests/cogos/test_per_channel_handler.py`

**Step 1: Write the integration test**

```python
"""Integration test for per-channel Discord sub-handler flow."""
from uuid import UUID, uuid4

from cogos.capabilities.procs import ProcsCapability
from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_child_receives_delivery_on_fine_grained_channel(tmp_path):
    """After parent spawns a child subscribed to a fine-grained channel,
    new messages on that channel create deliveries for the child."""
    repo = _repo(tmp_path)

    # Create parent process (the discord-handler)
    parent = Process(
        name="discord-handler",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(parent)

    # Create catch-all and fine-grained channels
    catch_all = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
    repo.upsert_channel(catch_all)

    fine = Channel(name="io:discord:message:12345", channel_type=ChannelType.NAMED)
    repo.upsert_channel(fine)

    # Parent has a handler on catch-all
    repo.create_handler(Handler(process=parent.id, channel=catch_all.id))

    # Parent spawns a child subscribed to fine-grained channel
    procs = ProcsCapability(repo, parent.id)
    child_handle = procs.spawn(
        name="discord-handler:12345",
        content="Handle messages from channel 12345",
        subscribe="io:discord:message:12345",
    )
    assert not hasattr(child_handle, "error"), f"Spawn failed: {child_handle}"

    # Simulate bridge writing a message to both channels
    payload = {"content": "hello", "channel_id": "12345", "author_id": "42"}
    repo.append_channel_message(ChannelMessage(
        channel=catch_all.id, sender_process=None, payload=payload,
    ))
    repo.append_channel_message(ChannelMessage(
        channel=fine.id, sender_process=None, payload=payload,
    ))

    # Child should have a pending delivery on the fine-grained channel
    child_proc = repo.get_process_by_name("discord-handler:12345")
    child_deliveries = repo.get_pending_deliveries(child_proc.id)
    assert len(child_deliveries) >= 1

    # Parent should also have a pending delivery on catch-all
    parent_deliveries = repo.get_pending_deliveries(parent.id)
    assert len(parent_deliveries) >= 1

    # Both should be RUNNABLE
    assert repo.get_process(child_proc.id).status == ProcessStatus.RUNNABLE
    assert repo.get_process(parent.id).status == ProcessStatus.RUNNABLE
```

**Step 2: Run test**

Run: `pytest tests/cogos/test_per_channel_handler.py -v`
Expected: PASS (this tests the integration of Tasks 1+2 together)

**Step 3: Commit**

```bash
git add tests/cogos/test_per_channel_handler.py
git commit -m "test: add integration test for per-channel discord sub-handler flow"
```

---

## Summary of changes

| Component | Change |
|---|---|
| `procs.spawn()` | New `subscribe` param creates Handler binding child to a channel |
| `DiscordBridge._relay_to_db` | Writes to both catch-all and fine-grained per-source channels |
| `Process` model | New `idle_timeout_ms` field |
| `SchedulerCapability` | New `reap_idle_processes()` method |
| Local executor + orchestrator | Wire reaping into scheduler tick |

The parent discord-handler process prompt (not in this plan) will need a template that:
1. Extracts `channel_id` / `author_id` from the message payload
2. Checks `procs.get(name=f"discord-handler:{id}")` — if alive, returns immediately
3. If not found, calls `procs.spawn(name=..., content=rendered_template, subscribe=f"io:discord:message:{id}", ...)` with delegated capabilities
