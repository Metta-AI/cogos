# Per-Process IO Channels Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give every CogOS process its own stdin/stdout/stderr channels with TTY forwarding to global io channels, accessible via `me` and `ProcessHandle`.

**Architecture:** Add `tty` field to Process model. Create `process:<name>:stdin/stdout/stderr` channels on spawn. Add `stdout()`/`stderr()`/`stdin()` to `MeCapability` and `ProcessHandle`. Replace executor's direct `io:*` publishing with `_publish_process_io()` that writes to per-process channels and optionally forwards to global `io:*`. Shell gets `attach` command and `--tty` flag on spawn.

**Tech Stack:** Existing CogOS models, `LocalRepository`, `Repository`, `prompt_toolkit`

---

### Task 1: Add `tty` field to Process model

**Files:**
- Modify: `src/cogos/db/models/process.py:49` (add tty field)
- Modify: `src/cogos/db/repository.py:252-300` (add tty to SQL INSERT/UPDATE)
- Modify: `src/cogos/db/repository.py:380-397` (add tty to _process_from_row)
- Test: `tests/cogos/shell/test_process_tty.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_process_tty.py`:

```python
"""Tests for Process tty field."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_process_tty_defaults_false():
    p = Process(name="test", mode=ProcessMode.ONE_SHOT)
    assert p.tty is False


def test_process_tty_persists(tmp_path):
    repo = LocalRepository(str(tmp_path))
    p = Process(name="test", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, tty=True)
    repo.upsert_process(p)
    loaded = repo.get_process_by_name("test")
    assert loaded.tty is True


def test_process_tty_false_by_default_persists(tmp_path):
    repo = LocalRepository(str(tmp_path))
    p = Process(name="test2", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(p)
    loaded = repo.get_process_by_name("test2")
    assert loaded.tty is False
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_process_tty.py -v`

**Step 3: Add tty field to Process model**

In `src/cogos/db/models/process.py`, add after line 49 (`clear_context`):

```python
    tty: bool = False  # forward stdio to global io channels
```

In `src/cogos/db/repository.py`, add `tty` to the INSERT column list (after `clear_context`), the VALUES list, the ON CONFLICT UPDATE list, the parameter list, and `_process_from_row`. The exact changes:

- Column list: add `, tty` after `clear_context`
- VALUES: add `, :tty` after `:clear_context`
- ON CONFLICT: add `tty = EXCLUDED.tty,` after `clear_context = EXCLUDED.clear_context,`
- Params: add `self._param("tty", p.tty),` after `clear_context` param
- `_process_from_row`: add `tty=row.get("tty", False),` after `clear_context`

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_process_tty.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/db/models/process.py src/cogos/db/repository.py tests/cogos/shell/test_process_tty.py
git commit -m "feat(io): add tty field to Process model"
```

---

### Task 2: Create per-process io channels on spawn

**Files:**
- Modify: `src/cogos/capabilities/procs.py:228-271` (create stdio channels after spawn channels)
- Test: `tests/cogos/shell/test_process_io_channels.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_process_io_channels.py`:

```python
"""Tests for per-process io channel creation on spawn."""

from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessCapability, ProcessMode, ProcessStatus
from cogos.capabilities.procs import ProcsCapability


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    # Create procs capability
    cap = Capability(name="procs", handler="cogos.capabilities.procs.ProcsCapability", enabled=True)
    repo.upsert_capability(cap)
    # Create parent process with procs capability
    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING, runner="local")
    repo.upsert_process(parent)
    repo.create_process_capability(ProcessCapability(process=parent.id, capability=cap.id, name="procs"))
    procs_cap = ProcsCapability(repo, parent.id)
    return repo, procs_cap


def test_spawn_creates_stdio_channels(tmp_path):
    repo, procs_cap = _setup(tmp_path)
    handle = procs_cap.spawn("worker", content="do stuff")
    assert not hasattr(handle, "error"), f"spawn failed: {handle}"

    for stream in ("stdin", "stdout", "stderr"):
        ch = repo.get_channel_by_name(f"process:worker:{stream}")
        assert ch is not None, f"process:worker:{stream} channel not created"


def test_spawn_with_tty(tmp_path):
    repo, procs_cap = _setup(tmp_path)
    handle = procs_cap.spawn("tty-worker", content="do stuff", tty=True)
    assert not hasattr(handle, "error"), f"spawn failed: {handle}"
    proc = repo.get_process_by_name("tty-worker")
    assert proc.tty is True
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_process_io_channels.py -v`

**Step 3: Modify procs.spawn()**

In `src/cogos/capabilities/procs.py`, add `tty: bool = False` parameter to `spawn()` method signature (after `detached`).

Set `tty=tty` on the child Process constructor.

After the spawn channel creation (after `self.repo.upsert_channel(recv_ch)` around line 251), add:

```python
        # Create per-process stdio channels
        for stream in ("stdin", "stdout", "stderr"):
            io_ch = Channel(
                name=f"process:{name}:{stream}",
                owner_process=child_id,
                channel_type=ChannelType.NAMED,
            )
            self.repo.upsert_channel(io_ch)
```

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_process_io_channels.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/procs.py tests/cogos/shell/test_process_io_channels.py
git commit -m "feat(io): create per-process stdin/stdout/stderr channels on spawn"
```

---

### Task 3: Add stdout/stderr/stdin to MeCapability

**Files:**
- Modify: `src/cogos/capabilities/me.py:136-161` (add methods)
- Test: `tests/cogos/shell/test_me_io.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_me_io.py`:

```python
"""Tests for MeCapability stdin/stdout/stderr methods."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.capabilities.me import MeCapability


def _setup(tmp_path, *, tty=False):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING, tty=tty)
    repo.upsert_process(proc)
    for stream in ("stdin", "stdout", "stderr"):
        repo.upsert_channel(Channel(name=f"process:worker:{stream}", owner_process=proc.id, channel_type=ChannelType.NAMED))
    # Create global io channels for tty tests
    for stream in ("stdout", "stderr"):
        repo.upsert_channel(Channel(name=f"io:{stream}", channel_type=ChannelType.NAMED))
    me = MeCapability(repo, proc.id)
    return repo, proc, me


def test_me_stdout(tmp_path):
    repo, proc, me = _setup(tmp_path)
    me.stdout("hello world")
    ch = repo.get_channel_by_name("process:worker:stdout")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "hello world"


def test_me_stderr(tmp_path):
    repo, proc, me = _setup(tmp_path)
    me.stderr("oops")
    ch = repo.get_channel_by_name("process:worker:stderr")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "oops"


def test_me_stdin(tmp_path):
    repo, proc, me = _setup(tmp_path)
    ch = repo.get_channel_by_name("process:worker:stdin")
    from cogos.db.models import ChannelMessage
    repo.append_channel_message(ChannelMessage(channel=ch.id, sender_process=None, payload={"text": "input line"}))
    result = me.stdin()
    assert result == "input line"


def test_me_stdin_empty(tmp_path):
    repo, proc, me = _setup(tmp_path)
    result = me.stdin()
    assert result is None


def test_me_stdout_tty_forwards(tmp_path):
    repo, proc, me = _setup(tmp_path, tty=True)
    me.stdout("hello tty")
    # Check per-process channel
    ch = repo.get_channel_by_name("process:worker:stdout")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1
    # Check global io channel
    io_ch = repo.get_channel_by_name("io:stdout")
    io_msgs = repo.list_channel_messages(io_ch.id)
    assert len(io_msgs) == 1
    assert io_msgs[0].payload["text"] == "hello tty"


def test_me_stdout_no_tty_no_forward(tmp_path):
    repo, proc, me = _setup(tmp_path, tty=False)
    me.stdout("hello no tty")
    io_ch = repo.get_channel_by_name("io:stdout")
    io_msgs = repo.list_channel_messages(io_ch.id)
    assert len(io_msgs) == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_me_io.py -v`

**Step 3: Add methods to MeCapability**

In `src/cogos/capabilities/me.py`, add these methods to `MeCapability` before `__repr__`:

```python
    def _process_name(self) -> str:
        proc = self.repo.get_process(self.process_id)
        return proc.name if proc else str(self.process_id)

    def _publish_stream(self, stream: str, text: str) -> None:
        """Publish to process:<name>:<stream> and optionally forward to io:<stream>."""
        from cogos.db.models import ChannelMessage
        name = self._process_name()
        ch = self.repo.get_channel_by_name(f"process:{name}:{stream}")
        if ch:
            self.repo.append_channel_message(ChannelMessage(
                channel=ch.id, sender_process=self.process_id,
                payload={"text": text, "process": name},
            ))
        # TTY forwarding
        proc = self.repo.get_process(self.process_id)
        if proc and proc.tty:
            io_ch = self.repo.get_channel_by_name(f"io:{stream}")
            if io_ch:
                self.repo.append_channel_message(ChannelMessage(
                    channel=io_ch.id, sender_process=self.process_id,
                    payload={"text": text, "process": name},
                ))

    def stdout(self, text: str) -> None:
        """Write to process stdout (and io:stdout if tty)."""
        self._publish_stream("stdout", text)

    def stderr(self, text: str) -> None:
        """Write to process stderr (and io:stderr if tty)."""
        self._publish_stream("stderr", text)

    def stdin(self, limit: int = 1) -> str | list[str] | None:
        """Read next message(s) from process stdin."""
        from cogos.db.models import ChannelMessage
        name = self._process_name()
        ch = self.repo.get_channel_by_name(f"process:{name}:stdin")
        if not ch:
            return None
        msgs = self.repo.list_channel_messages(ch.id, limit=limit)
        if not msgs:
            return None
        texts = [m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload) for m in msgs]
        return texts[0] if limit == 1 else texts
```

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_me_io.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/me.py tests/cogos/shell/test_me_io.py
git commit -m "feat(io): add stdout/stderr/stdin methods to MeCapability"
```

---

### Task 4: Add stdin/stdout/stderr to ProcessHandle

**Files:**
- Modify: `src/cogos/capabilities/process_handle.py:19-114` (add methods)
- Test: `tests/cogos/shell/test_handle_io.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_handle_io.py`:

```python
"""Tests for ProcessHandle stdin/stdout/stderr methods."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.capabilities.process_handle import ProcessHandle


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
    repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING, parent_process=parent.id)
    repo.upsert_process(child)
    for stream in ("stdin", "stdout", "stderr"):
        repo.upsert_channel(Channel(name=f"process:child:{stream}", owner_process=child.id, channel_type=ChannelType.NAMED))
    handle = ProcessHandle(repo=repo, caller_process_id=parent.id, process=child, send_channel=None, recv_channel=None)
    return repo, handle


def test_handle_stdin_writes(tmp_path):
    repo, handle = _setup(tmp_path)
    handle.stdin("hello child")
    ch = repo.get_channel_by_name("process:child:stdin")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "hello child"


def test_handle_stdout_reads(tmp_path):
    repo, handle = _setup(tmp_path)
    ch = repo.get_channel_by_name("process:child:stdout")
    repo.append_channel_message(ChannelMessage(channel=ch.id, sender_process=None, payload={"text": "output"}))
    result = handle.stdout()
    assert result == "output"


def test_handle_stderr_reads(tmp_path):
    repo, handle = _setup(tmp_path)
    ch = repo.get_channel_by_name("process:child:stderr")
    repo.append_channel_message(ChannelMessage(channel=ch.id, sender_process=None, payload={"text": "error msg"}))
    result = handle.stderr()
    assert result == "error msg"


def test_handle_stdout_empty(tmp_path):
    repo, handle = _setup(tmp_path)
    assert handle.stdout() is None
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_handle_io.py -v`

**Step 3: Add methods to ProcessHandle**

In `src/cogos/capabilities/process_handle.py`, add before `__repr__`:

```python
    def stdin(self, text: str) -> dict:
        """Write to child's stdin channel."""
        ch = self._repo.get_channel_by_name(f"process:{self._process.name}:stdin")
        if not ch:
            return {"error": f"No stdin channel for {self._process.name}"}
        msg = ChannelMessage(channel=ch.id, sender_process=self._caller_id, payload={"text": text})
        msg_id = self._repo.append_channel_message(msg)
        return {"id": str(msg_id)}

    def stdout(self, limit: int = 1) -> str | list[str] | None:
        """Read from child's stdout channel."""
        ch = self._repo.get_channel_by_name(f"process:{self._process.name}:stdout")
        if not ch:
            return None
        msgs = self._repo.list_channel_messages(ch.id, limit=limit)
        if not msgs:
            return None
        texts = [m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload) for m in msgs]
        return texts[0] if limit == 1 else texts

    def stderr(self, limit: int = 1) -> str | list[str] | None:
        """Read from child's stderr channel."""
        ch = self._repo.get_channel_by_name(f"process:{self._process.name}:stderr")
        if not ch:
            return None
        msgs = self._repo.list_channel_messages(ch.id, limit=limit)
        if not msgs:
            return None
        texts = [m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload) for m in msgs]
        return texts[0] if limit == 1 else texts
```

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_handle_io.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/process_handle.py tests/cogos/shell/test_handle_io.py
git commit -m "feat(io): add stdin/stdout/stderr to ProcessHandle"
```

---

### Task 5: Wire executor to use per-process io channels

**Files:**
- Modify: `src/cogos/executor/handler.py:348-362` (replace `_publish_io` with `_publish_process_io`)
- Modify: `src/cogos/executor/handler.py:554-557` (run_code output)
- Modify: `src/cogos/executor/handler.py:592-595` (final assistant text)
- Modify: `src/cogos/executor/handler.py:647-651` (exception)
- Test: `tests/cogos/shell/test_executor_io.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_executor_io.py`:

```python
"""Tests for executor per-process io channel publishing."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.executor.handler import _publish_process_io


def _setup(tmp_path, *, tty=False):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="test-proc", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING, tty=tty)
    repo.upsert_process(proc)
    for stream in ("stdout", "stderr"):
        repo.upsert_channel(Channel(name=f"process:test-proc:{stream}", owner_process=proc.id, channel_type=ChannelType.NAMED))
        repo.upsert_channel(Channel(name=f"io:{stream}", channel_type=ChannelType.NAMED))
    return repo, proc


def test_publish_process_io_writes_to_process_channel(tmp_path):
    repo, proc = _setup(tmp_path)
    _publish_process_io(repo, proc, "stdout", "hello")
    ch = repo.get_channel_by_name("process:test-proc:stdout")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "hello"


def test_publish_process_io_no_tty_no_global(tmp_path):
    repo, proc = _setup(tmp_path, tty=False)
    _publish_process_io(repo, proc, "stdout", "hello")
    io_ch = repo.get_channel_by_name("io:stdout")
    assert len(repo.list_channel_messages(io_ch.id)) == 0


def test_publish_process_io_tty_forwards(tmp_path):
    repo, proc = _setup(tmp_path, tty=True)
    _publish_process_io(repo, proc, "stdout", "hello tty")
    io_ch = repo.get_channel_by_name("io:stdout")
    msgs = repo.list_channel_messages(io_ch.id)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "hello tty"


def test_publish_process_io_empty_text_skipped(tmp_path):
    repo, proc = _setup(tmp_path)
    _publish_process_io(repo, proc, "stdout", "")
    ch = repo.get_channel_by_name("process:test-proc:stdout")
    assert len(repo.list_channel_messages(ch.id)) == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_executor_io.py -v`

**Step 3: Replace _publish_io with _publish_process_io**

In `src/cogos/executor/handler.py`, replace the existing `_publish_io` function with:

```python
def _publish_io(repo, process, channel_name: str, text: str) -> None:
    """Publish text to a named channel if it exists."""
    if not text or not text.strip():
        return
    try:
        ch = repo.get_channel_by_name(channel_name)
        if ch:
            repo.append_channel_message(ChannelMessage(
                channel=ch.id,
                sender_process=process.id,
                payload={"text": text, "process": process.name},
            ))
    except Exception:
        logger.debug("Failed to publish to %s", channel_name, exc_info=True)


def _publish_process_io(repo, process, stream: str, text: str) -> None:
    """Publish to process:<name>:<stream> and optionally forward to io:<stream>."""
    _publish_io(repo, process, f"process:{process.name}:{stream}", text)
    if process.tty:
        _publish_io(repo, process, f"io:{stream}", text)
```

Then replace all direct `_publish_io(repo, process, "io:stdout", ...)` and `_publish_io(repo, process, "io:stderr", ...)` calls in `execute_process` with `_publish_process_io(repo, process, "stdout", ...)` and `_publish_process_io(repo, process, "stderr", ...)`.

Specifically:
- The `run_code` result publish: `_publish_process_io(repo, process, "stdout", result)`
- The final assistant text publish: `_publish_process_io(repo, process, "stderr", block["text"])`
- The exception publish: `_publish_process_io(repo, process, "stderr", f"[{process.name}] {exc}")`

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_executor_io.py -v`
Expected: PASS

**Step 5: Run all existing tests to verify no regressions**

Run: `uv run --extra dev pytest tests/cogos/shell/ -v`

**Step 6: Commit**

```bash
git add src/cogos/executor/handler.py tests/cogos/shell/test_executor_io.py
git commit -m "feat(io): executor uses per-process io channels with TTY forwarding"
```

---

### Task 6: Shell attach command

**Files:**
- Create: `src/cogos/shell/commands/attach.py`
- Modify: `src/cogos/shell/commands/__init__.py:83-101` (register attach)
- Test: `tests/cogos/shell/test_attach.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_attach.py`:

```python
"""Tests for shell attach command."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.attach import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="worker", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda")
    repo.upsert_process(proc)
    for stream in ("stdin", "stdout", "stderr"):
        repo.upsert_channel(Channel(name=f"process:worker:{stream}", owner_process=proc.id, channel_type=ChannelType.NAMED))
    # Add a message to stdout
    ch = repo.get_channel_by_name("process:worker:stdout")
    repo.append_channel_message(ChannelMessage(channel=ch.id, sender_process=proc.id, payload={"text": "hello from worker"}))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_attach_not_found(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "attach nonexistent")
    assert "not found" in output.lower()


def test_attach_no_args(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "attach")
    assert "usage" in output.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_attach.py -v`

**Step 3: Implement attach command**

Create `src/cogos/shell/commands/attach.py`:

```python
"""Attach command — tail a process's stdout/stderr."""

from __future__ import annotations

import time

from cogos.shell.commands import CommandRegistry, ShellState

_DIM = "\033[90m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_RESET = "\033[0m"


def register(reg: CommandRegistry) -> None:

    @reg.register("attach", help="Attach to a process: attach [-i] <name>")
    def attach(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: attach [-i] <name>"

        interactive = "-i" in args
        name = [a for a in args if a != "-i"][0] if args else ""

        if not name:
            return "Usage: attach [-i] <name>"

        proc = state.repo.get_process_by_name(name)
        if not proc:
            return f"attach: not found: {name}"

        stdout_ch = state.repo.get_channel_by_name(f"process:{name}:stdout")
        stderr_ch = state.repo.get_channel_by_name(f"process:{name}:stderr")
        stdin_ch = state.repo.get_channel_by_name(f"process:{name}:stdin") if interactive else None

        if not stdout_ch and not stderr_ch:
            return f"attach: no io channels for {name}"

        # Track cursors from now (don't replay history)
        from cogos.db.models import ChannelMessage
        stdout_cursor = None
        stderr_cursor = None
        if stdout_ch:
            msgs = state.repo.list_channel_messages(stdout_ch.id, limit=1)
            stdout_cursor = msgs[-1].created_at if msgs else None
        if stderr_ch:
            msgs = state.repo.list_channel_messages(stderr_ch.id, limit=1)
            stderr_cursor = msgs[-1].created_at if msgs else None

        print(f"{_DIM}Attached to {name} (ctrl+c to detach){_RESET}")

        try:
            while True:
                found = False
                if stdout_ch:
                    msgs = state.repo.list_channel_messages(stdout_ch.id, limit=50, since=stdout_cursor)
                    for m in msgs:
                        text = m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload)
                        if text:
                            print(f"{_GREEN}stdout{_RESET} {text}")
                        stdout_cursor = m.created_at
                        found = True
                if stderr_ch:
                    msgs = state.repo.list_channel_messages(stderr_ch.id, limit=50, since=stderr_cursor)
                    for m in msgs:
                        text = m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload)
                        if text:
                            print(f"{_RED}stderr{_RESET} {text}")
                        stderr_cursor = m.created_at
                        found = True

                if interactive and stdin_ch:
                    try:
                        import select
                        import sys
                        if select.select([sys.stdin], [], [], 0)[0]:
                            line = sys.stdin.readline().strip()
                            if line:
                                state.repo.append_channel_message(ChannelMessage(
                                    channel=stdin_ch.id, sender_process=None,
                                    payload={"text": line, "source": "shell"},
                                ))
                    except Exception:
                        pass

                if not found:
                    time.sleep(1)
        except KeyboardInterrupt:
            return f"{_DIM}Detached from {name}{_RESET}"
```

In `src/cogos/shell/commands/__init__.py`, add the import to `build_registry()`:

```python
    from cogos.shell.commands.attach import register as register_attach
    register_attach(reg)
```

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_attach.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/shell/commands/attach.py src/cogos/shell/commands/__init__.py tests/cogos/shell/test_attach.py
git commit -m "feat(shell): add attach command for per-process io"
```

---

### Task 7: Shell spawn --tty, ps TTY column, llm tty

**Files:**
- Modify: `src/cogos/shell/commands/procs.py:74-120` (add --tty to spawn, TTY column to ps)
- Modify: `src/cogos/shell/commands/llm.py:85-97` (set tty=True on temp process)
- Test: `tests/cogos/shell/test_shell_tty.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_shell_tty.py`:

```python
"""Tests for shell TTY integration."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.procs import register as register_procs


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_process(Process(name="daemon", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda"))
    repo.upsert_process(Process(name="shell-job", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING, runner="local", tty=True))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register_procs(reg)
    return state, reg, repo


def test_ps_shows_tty_column(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ps --all")
    assert "TTY" in output
    assert "*" in output  # shell-job has tty=True


def test_spawn_tty_flag(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "spawn worker --tty")
    p = repo.get_process_by_name("worker")
    assert p is not None
    assert p.tty is True


def test_spawn_no_tty_default(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "spawn worker2")
    p = repo.get_process_by_name("worker2")
    assert p.tty is False
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_shell_tty.py -v`

**Step 3: Update shell procs.py**

In `src/cogos/shell/commands/procs.py`:

Update `_format_process_table` to add TTY column:

```python
def _format_process_table(procs: list[Process]) -> str:
    if not procs:
        return "(no processes)"
    lines = [f"{'NAME':<24} {'STATUS':<12} {'MODE':<10} {'RUNNER':<8} {'TTY':<5} {'PRI':>5}"]
    lines.append("-" * 68)
    for p in procs:
        color = _STATUS_COLORS.get(p.status.value, "")
        tty = "*" if p.tty else ""
        lines.append(
            f"{p.name:<24} {color}{p.status.value:<12}{_RESET} "
            f"{p.mode.value:<10} {p.runner:<8} {tty:<5} {p.priority:>5.1f}"
        )
    return "\n".join(lines)
```

In `spawn`, add `--tty` flag parsing and set `tty=tty` on Process:

Add `tty = False` to the defaults, add `elif args[i] == "--tty": tty = True; i += 1` to the arg parser, and add `tty=tty` to the Process constructor.

In `src/cogos/shell/commands/llm.py`, set `tty=True` on the temp process (in `_execute_prompt`, on the `Process(...)` constructor).

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_shell_tty.py -v`
Expected: PASS

**Step 5: Run all shell tests**

Run: `uv run --extra dev pytest tests/cogos/shell/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/cogos/shell/commands/procs.py src/cogos/shell/commands/llm.py tests/cogos/shell/test_shell_tty.py
git commit -m "feat(shell): spawn --tty, ps TTY column, llm sets tty=True"
```

---

### Task 8: Create process io channels for image-booted processes

**Files:**
- Modify: `src/cogos/image/apply.py:117-165` (create stdio channels for each process)
- Test: `tests/cogos/shell/test_image_io.py`

**Step 1: Write failing test**

Create `tests/cogos/shell/test_image_io.py`:

```python
"""Tests for image boot creating per-process io channels."""

from cogos.db.local_repository import LocalRepository
from cogos.image.apply import apply_image
from cogos.image.spec import ImageSpec


def test_image_boot_creates_process_io_channels(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(
        processes=[{
            "name": "scheduler",
            "mode": "daemon",
            "content": "run scheduler",
            "runner": "lambda",
            "priority": 100.0,
            "capabilities": [],
            "handlers": [],
        }],
    )
    apply_image(spec, repo)

    for stream in ("stdin", "stdout", "stderr"):
        ch = repo.get_channel_by_name(f"process:scheduler:{stream}")
        assert ch is not None, f"process:scheduler:{stream} not created"
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/cogos/shell/test_image_io.py -v`

**Step 3: Add io channel creation to apply_image**

In `src/cogos/image/apply.py`, inside the process creation loop (after `counts["processes"] += 1` around line 165), add:

```python
        # Create per-process stdio channels
        for stream in ("stdin", "stdout", "stderr"):
            io_ch_name = f"process:{proc_dict['name']}:{stream}"
            if repo.get_channel_by_name(io_ch_name) is None:
                repo.upsert_channel(Channel(
                    name=io_ch_name, owner_process=pid, channel_type=ChannelType.NAMED,
                ))
```

**Step 4: Run test**

Run: `uv run --extra dev pytest tests/cogos/shell/test_image_io.py -v`
Expected: PASS

**Step 5: Run existing image tests to check for regressions**

Run: `uv run --extra dev pytest tests/cogos/test_image_apply.py tests/cogos/test_image_e2e.py -v`

**Step 6: Commit**

```bash
git add src/cogos/image/apply.py tests/cogos/shell/test_image_io.py
git commit -m "feat(io): image boot creates per-process stdin/stdout/stderr channels"
```

---

### Task 9: Tab completion for attach and integration test

**Files:**
- Modify: `src/cogos/shell/completer.py:14-16` (add attach to PROC_COMMANDS)
- Create: `tests/cogos/shell/test_io_integration.py`

**Step 1: Update completer**

In `src/cogos/shell/completer.py`, add `"attach"` to `_PROC_COMMANDS`:

```python
_PROC_COMMANDS = {"kill", "attach"}
```

**Step 2: Write integration test**

Create `tests/cogos/shell/test_io_integration.py`:

```python
"""Integration test for per-process IO end-to-end."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Capability, Channel, ChannelMessage, ChannelType,
    Process, ProcessCapability, ProcessMode, ProcessStatus,
)
from cogos.capabilities.me import MeCapability
from cogos.capabilities.procs import ProcsCapability


def test_parent_child_stdio(tmp_path):
    """Parent spawns child, writes to child stdin, child writes to stdout, parent reads."""
    repo = LocalRepository(str(tmp_path))

    # Set up procs capability
    cap = Capability(name="procs", handler="cogos.capabilities.procs.ProcsCapability", enabled=True)
    repo.upsert_capability(cap)

    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
    repo.upsert_process(parent)
    repo.create_process_capability(ProcessCapability(process=parent.id, capability=cap.id, name="procs"))

    procs = ProcsCapability(repo, parent.id)
    handle = procs.spawn("child", content="do work")

    # Parent writes to child's stdin
    handle.stdin("input data")

    # Child reads its stdin via me capability
    child_proc = repo.get_process_by_name("child")
    me = MeCapability(repo, child_proc.id)
    input_msg = me.stdin()
    assert input_msg == "input data"

    # Child writes to its stdout
    me.stdout("result data")

    # Parent reads child's stdout
    output = handle.stdout()
    assert output == "result data"


def test_tty_forwarding_e2e(tmp_path):
    """TTY process output forwards to global io:stdout."""
    repo = LocalRepository(str(tmp_path))

    # Create global io channels
    for name in ("io:stdout", "io:stderr"):
        repo.upsert_channel(Channel(name=name, channel_type=ChannelType.NAMED))

    cap = Capability(name="procs", handler="cogos.capabilities.procs.ProcsCapability", enabled=True)
    repo.upsert_capability(cap)

    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
    repo.upsert_process(parent)
    repo.create_process_capability(ProcessCapability(process=parent.id, capability=cap.id, name="procs"))

    procs = ProcsCapability(repo, parent.id)
    handle = procs.spawn("tty-child", content="do work", tty=True)

    child_proc = repo.get_process_by_name("tty-child")
    me = MeCapability(repo, child_proc.id)
    me.stdout("visible output")

    # Should appear on process channel
    ch = repo.get_channel_by_name("process:tty-child:stdout")
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1

    # Should also appear on global io:stdout
    io_ch = repo.get_channel_by_name("io:stdout")
    io_msgs = repo.list_channel_messages(io_ch.id)
    assert len(io_msgs) == 1
    assert io_msgs[0].payload["text"] == "visible output"
```

**Step 3: Run tests**

Run: `uv run --extra dev pytest tests/cogos/shell/test_io_integration.py tests/cogos/shell/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/cogos/shell/completer.py tests/cogos/shell/test_io_integration.py
git commit -m "feat(io): attach tab completion and end-to-end integration test"
```
