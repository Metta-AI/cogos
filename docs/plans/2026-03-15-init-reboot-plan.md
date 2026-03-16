# Init Process & Reboot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace scattered add_process() declarations with a single init process that spawns everything, add cascade kill, detach, reboot CLI command, and dashboard reboot button.

**Architecture:** Init is a python-executor one-shot process that spawns infrastructure + apps + coglets. Cascade kill disables all children when a parent is killed. Reboot kills init (cascading), clears process table, re-creates init. CLI and dashboard both call the same reboot function.

**Tech Stack:** Python, CogOS Capability/Repository, FastAPI dashboard.

**Reference:** `docs/plans/2026-03-15-init-reboot-design.md`

---

### Task 1: Cascade Kill in Repository

Add recursive cascade kill to `update_process_status` when setting DISABLED.

**Files:**
- Modify: `src/cogos/db/local_repository.py:447-458`
- Modify: `src/cogos/db/repository.py` (if it has update_process_status)
- Test: `tests/cogos/test_cascade_kill.py`

**Step 1: Write the failing test**

```python
# tests/cogos/test_cascade_kill.py
from uuid import uuid4
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_cascade_kill_disables_children(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                    parent_process=parent_id)
    child_id = repo.upsert_process(child)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    assert repo.get_process(parent_id).status == ProcessStatus.DISABLED
    assert repo.get_process(child_id).status == ProcessStatus.DISABLED


def test_cascade_kill_recursive(tmp_path):
    repo = LocalRepository(str(tmp_path))
    root = Process(name="root", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    root_id = repo.upsert_process(root)
    mid = Process(name="mid", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE,
                  parent_process=root_id)
    mid_id = repo.upsert_process(mid)
    leaf = Process(name="leaf", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                   parent_process=mid_id)
    leaf_id = repo.upsert_process(leaf)

    repo.update_process_status(root_id, ProcessStatus.DISABLED)

    assert repo.get_process(root_id).status == ProcessStatus.DISABLED
    assert repo.get_process(mid_id).status == ProcessStatus.DISABLED
    assert repo.get_process(leaf_id).status == ProcessStatus.DISABLED


def test_cascade_kill_does_not_affect_siblings(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child_a = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                      parent_process=parent_id)
    child_a_id = repo.upsert_process(child_a)
    sibling = Process(name="sibling", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    sibling_id = repo.upsert_process(sibling)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    assert repo.get_process(sibling_id).status == ProcessStatus.RUNNABLE


def test_non_disable_does_not_cascade(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                    parent_process=parent_id)
    child_id = repo.upsert_process(child)

    repo.update_process_status(parent_id, ProcessStatus.COMPLETED)

    assert repo.get_process(child_id).status == ProcessStatus.RUNNABLE
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_cascade_kill.py -v -x`
Expected: FAIL — children not disabled

**Step 3: Write minimal implementation**

Modify `update_process_status` in `src/cogos/db/local_repository.py` (line ~447):

```python
    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        with self._writing():
            process = self._processes.get(process_id)
            if process is None:
                return False
            process.status = status
            if status == ProcessStatus.RUNNABLE:
                process.runnable_since = process.runnable_since or datetime.utcnow()
            else:
                process.runnable_since = None
            process.updated_at = datetime.utcnow()
            # Cascade: if disabling, recursively disable all children
            if status == ProcessStatus.DISABLED:
                self._cascade_disable(process_id)
            return True

    def _cascade_disable(self, parent_id: UUID) -> None:
        """Recursively disable all child processes."""
        children = [p for p in self._processes.values() if p.parent_process == parent_id]
        for child in children:
            if child.status not in (ProcessStatus.DISABLED, ProcessStatus.COMPLETED):
                child.status = ProcessStatus.DISABLED
                child.runnable_since = None
                child.updated_at = datetime.utcnow()
                self._cascade_disable(child.id)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_cascade_kill.py -v -x`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/cogos/db/local_repository.py tests/cogos/test_cascade_kill.py
git commit -m "feat(cogos): add cascade kill — disabling a parent recursively disables children"
```

---

### Task 2: Detach — spawn(detached=True) and procs.detach()

**Files:**
- Modify: `src/cogos/capabilities/procs.py:123-157`
- Test: `tests/cogos/test_cascade_kill.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_cascade_kill.py
from cogos.capabilities.procs import ProcsCapability
from cogos.image.spec import ImageSpec
from cogos.image.apply import apply_image


def _setup_with_procs(tmp_path):
    """Create repo with procs capability and an init + parent process."""
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)
    init_proc = Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
    init_id = repo.upsert_process(init_proc)
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE,
                     parent_process=init_id)
    parent_id = repo.upsert_process(parent)
    return repo, init_id, parent_id


def test_spawn_detached_sets_init_parent(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="detached-child", content="hello", detached=True)
    assert not hasattr(result, "error") or result.error is None
    child = repo.get_process_by_name("detached-child")
    assert child.parent_process == init_id


def test_spawn_normal_sets_caller_parent(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="normal-child", content="hello")
    child = repo.get_process_by_name("normal-child")
    assert child.parent_process == parent_id


def test_detach_reparents_to_init(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="child", content="hello")
    child = repo.get_process_by_name("child")
    assert child.parent_process == parent_id

    procs.detach(str(child.id))
    child = repo.get_process_by_name("child")
    assert child.parent_process == init_id


def test_cascade_kill_skips_detached(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    procs.spawn(name="attached", content="a")
    procs.spawn(name="detached", content="d", detached=True)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    assert repo.get_process_by_name("attached").status == ProcessStatus.DISABLED
    assert repo.get_process_by_name("detached").status == ProcessStatus.RUNNABLE
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_cascade_kill.py::test_spawn_detached_sets_init_parent -v -x`
Expected: FAIL — `TypeError: spawn() got an unexpected keyword argument 'detached'`

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/procs.py`, add `detached: bool = False` parameter to `spawn()` and add the `detach()` method. Also add `"detach"` to `ALL_OPS`.

For spawn, when `detached=True`, look up the init process and use its ID as parent:

```python
    def _init_process_id(self) -> UUID | None:
        """Find the init process ID."""
        init = self.repo.get_process_by_name("init")
        return init.id if init else None
```

In spawn, change the parent_process assignment:

```python
        if detached:
            init_id = self._init_process_id()
            parent_id = init_id if init_id else self.process_id
        else:
            parent_id = self.process_id

        child = Process(
            ...
            parent_process=parent_id,
            ...
        )
```

Add detach method:

```python
    def detach(self, process_id: str) -> ProcessDetail | ProcessError:
        """Reparent a child process to init."""
        self._check("detach")
        target = self.repo.get_process(UUID(process_id))
        if target is None:
            return ProcessError(error="process not found")
        init_id = self._init_process_id()
        if init_id is None:
            return ProcessError(error="init process not found")
        target.parent_process = init_id
        self.repo.upsert_process(target)
        return ProcessDetail(
            id=str(target.id), name=target.name, mode=target.mode.value,
            status=target.status.value, priority=target.priority, runner=target.runner,
            parent_process=str(init_id),
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_cascade_kill.py -v -x`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add src/cogos/capabilities/procs.py tests/cogos/test_cascade_kill.py
git commit -m "feat(cogos): add detached spawn and procs.detach() for reparenting to init"
```

---

### Task 3: Reboot Function

**Files:**
- Create: `src/cogos/runtime/reboot.py`
- Test: `tests/cogos/test_reboot.py`

**Step 1: Write the failing test**

```python
# tests/cogos/test_reboot.py
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.runtime.reboot import reboot


def test_reboot_clears_processes_and_creates_init(tmp_path):
    repo = LocalRepository(str(tmp_path))

    # Pre-populate with some processes
    init_proc = Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
    repo.upsert_process(init_proc)
    child = Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING,
                    parent_process=init_proc.id)
    repo.upsert_process(child)

    result = reboot(repo)
    assert result["cleared_processes"] >= 2

    # Only init should exist, and it should be RUNNABLE
    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"
    assert procs[0].status == ProcessStatus.RUNNABLE


def test_reboot_preserves_files(tmp_path):
    from cogos.files.store import FileStore
    repo = LocalRepository(str(tmp_path))
    store = FileStore(repo)
    store.upsert("test/file.md", "hello", source="test")

    reboot(repo)

    assert store.get_content("test/file.md") == "hello"


def test_reboot_with_no_existing_processes(tmp_path):
    repo = LocalRepository(str(tmp_path))
    result = reboot(repo)
    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_reboot.py -v -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.runtime.reboot'`

**Step 3: Write minimal implementation**

```python
# src/cogos/runtime/reboot.py
"""Reboot: kill all processes, clear process table, re-create init."""

from __future__ import annotations

import logging
from uuid import UUID

from cogos.db.models import Process, ProcessMode, ProcessStatus

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{cogos/init.py}"


def reboot(repo) -> dict:
    """Kill all processes, clear process state, create fresh init process.

    Preserves: files, coglets, channels, schemas, resources, cron.
    Clears: processes, runs, deliveries, handlers, process_capabilities.
    """
    # 1. Find and kill init (cascade kills everything)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 2. Count what we're clearing
    all_procs = repo.list_processes(limit=10000)
    cleared = len(all_procs)

    # 3. Clear process-related tables
    _clear_process_tables(repo)

    # 4. Create fresh init process
    init_proc = Process(
        name="init",
        mode=ProcessMode.ONE_SHOT,
        content=INIT_PROCESS_CONTENT,
        executor="python",
        priority=200.0,  # highest priority — runs first
        runner="lambda",
        status=ProcessStatus.RUNNABLE,
    )
    repo.upsert_process(init_proc)

    logger.info("Reboot complete: cleared %d processes, init queued", cleared)
    return {"cleared_processes": cleared}


def _clear_process_tables(repo) -> None:
    """Clear all process-related data."""
    # Clear in dependency order
    if hasattr(repo, "_runs"):
        # LocalRepository
        repo._runs.clear()
        repo._deliveries.clear()
        repo._handlers.clear()
        repo._process_capabilities.clear()
        repo._processes.clear()
        repo._persist()
    else:
        # SQL repository — use execute
        for table in [
            "cogos_trace", "cogos_delivery", "cogos_run",
            "cogos_handler", "cogos_process_capability", "cogos_process",
        ]:
            try:
                repo.execute(f"DELETE FROM {table}")
            except Exception:
                pass
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_reboot.py -v -x`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/cogos/runtime/reboot.py tests/cogos/test_reboot.py
git commit -m "feat(cogos): add reboot function — kill cascade, clear processes, re-create init"
```

---

### Task 4: CLI Command — cogos reboot

**Files:**
- Modify: `src/cogos/cli/__main__.py`
- Test: manual — `USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha reboot -y`

**Step 1: Add the command**

Add after the existing `reload` command in `src/cogos/cli/__main__.py`:

```python
@cogos.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def reboot(ctx: click.Context, yes: bool):
    """Kill all processes and restart from init.

    Preserves files, coglets, channels. Clears all processes and runs.
    """
    from cogos.runtime.reboot import reboot as do_reboot

    if not yes:
        click.confirm("This will kill all processes and restart from init. Continue?", abort=True)

    repo = _repo()
    result = do_reboot(repo)
    click.echo(f"Reboot complete: cleared {result['cleared_processes']} processes, init queued")
```

Note: the existing `reload` command is also named `reboot` — check that there's no name collision. The existing one is named `reload`, so we're fine.

**Step 2: Test manually**

Run: `USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha reboot -y`
Expected: Output like "Reboot complete: cleared N processes, init queued"

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "feat(cogos): add 'cogos reboot' CLI command"
```

---

### Task 5: Dashboard Reboot Endpoint

**Files:**
- Modify: `src/dashboard/routers/processes.py`
- Test: `tests/dashboard/test_routers_core.py` (or new test file)

**Step 1: Write the failing test**

```python
# tests/dashboard/test_reboot.py
from fastapi.testclient import TestClient
from dashboard.app import create_app
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_reboot_endpoint(tmp_path):
    repo = LocalRepository(str(tmp_path))
    # Add a process
    proc = Process(name="test", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    app = create_app(repo=repo)
    client = TestClient(app)
    resp = client.post("/api/reboot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cleared_processes"] >= 1

    # Verify init exists
    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/dashboard/test_reboot.py -v -x`
Expected: FAIL — 404 or endpoint not found

**Step 3: Write minimal implementation**

Add to `src/dashboard/routers/processes.py`:

```python
from cogos.runtime.reboot import reboot as do_reboot

@router.post("/reboot")
def reboot_system():
    """Kill all processes, clear process state, re-create init."""
    repo = get_repo()
    result = do_reboot(repo)
    return result
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/dashboard/test_reboot.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add src/dashboard/routers/processes.py tests/dashboard/test_reboot.py
git commit -m "feat(dashboard): add POST /api/reboot endpoint"
```

---

### Task 6: Init Process — Image Declaration and Boot Script

**Files:**
- Modify: `images/cogent-v1/init/processes.py`
- Create: `images/cogent-v1/cogos/init.py` (the boot script content, stored as a file)
- Test: `tests/cogos/test_reboot.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_reboot.py
from cogos.image.spec import load_image
from cogos.image.apply import apply_image
from pathlib import Path


def test_image_declares_init_process(tmp_path):
    repo = LocalRepository(str(tmp_path))
    image_dir = Path(__file__).resolve().parents[2] / "images" / "cogent-v1"
    spec = load_image(image_dir)
    apply_image(spec, repo)

    init = repo.get_process_by_name("init")
    assert init is not None
    assert init.executor == "python"
    assert init.mode.value == "one_shot"
    assert init.priority >= 100


def test_image_only_declares_init_process(tmp_path):
    """No other top-level processes should be declared — init spawns them."""
    repo = LocalRepository(str(tmp_path))
    image_dir = Path(__file__).resolve().parents[2] / "images" / "cogent-v1"
    spec = load_image(image_dir)
    apply_image(spec, repo)

    procs = repo.list_processes()
    top_level = [p for p in procs if p.parent_process is None]
    assert len(top_level) == 1
    assert top_level[0].name == "init"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_reboot.py::test_image_declares_init_process -v -x`
Expected: FAIL — init process doesn't exist or has wrong executor

**Step 3: Write minimal implementation**

Replace `images/cogent-v1/init/processes.py` with:

```python
# Only the init process is declared statically.
# All other processes are spawned by init at runtime.

add_process(
    "init",
    mode="one_shot",
    content="@{cogos/init.py}",
    executor="python",
    runner="lambda",
    priority=200.0,
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "secrets", "stdlib", "coglet_factory", "coglet",
    ],
)
```

Remove `add_process()` calls from all app init scripts:
- `images/cogent-v1/apps/newsfromthefront/init/processes.py` — keep channels/schemas, remove `add_process()`
- `images/cogent-v1/apps/supervisor/init/processes.py` — keep schema/channel, remove `add_process()`
- `images/cogent-v1/apps/fibonacci/init/processes.py` — remove `add_process()` (check what else is there)
- `images/cogent-v1/apps/secret-audit/init/processes.py` — remove `add_process()` (check what else is there)

Create `images/cogent-v1/cogos/init.py` — the boot script. This is stored as a file in the file store and referenced by `@{cogos/init.py}` in the init process content. It's Python code that runs in the sandbox:

```python
# CogOS Init — spawns all processes and coglets.
#
# Infrastructure
scheduler_prompt = file.read("cogos/lib/scheduler.md").content
procs.spawn("scheduler", mode="daemon", content=scheduler_prompt, priority=100.0,
    capabilities={"scheduler/match_channel_messages": None, "scheduler/select_processes": None,
                   "scheduler/dispatch_process": None, "scheduler/unblock_processes": None,
                   "scheduler/kill_process": None, "channels": None})

supervisor_prompt = file.read("apps/supervisor/supervisor.md").content
procs.spawn("supervisor", mode="daemon", content=supervisor_prompt, priority=8.0,
    capabilities={"me": None, "procs": None, "dir": None, "file": None, "discord": None,
                   "channels": None, "secrets": None, "stdlib": None, "alerts": None, "email": None},
    subscribe="supervisor:help")

discord_prompt = file.read("cogos/io/discord/dispatch.md").content
procs.spawn("discord-handle-message", mode="daemon", content=discord_prompt, priority=10.0,
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    capabilities={"discord": None, "channels": None, "stdlib": None, "procs": None, "file": None},
    subscribe="io:discord:dm")

# Apps
nftf_prompt = file.read("apps/newsfromthefront/newsfromthefront.md").content
procs.spawn("newsfromthefront", mode="daemon", content=nftf_prompt, priority=15.0,
    capabilities={"me": None, "procs": None, "dir": None, "file": None, "channels": None,
                   "discord": None, "web_search": None, "secrets": None, "stdlib": None},
    subscribe="newsfromthefront:tick")

# Coglets — run all executable coglets
coglets = coglet_factory.list()
for c in coglets:
    info = coglet_factory.get(c.coglet_id)
    # Only run coglets that have entrypoints (skip data-only coglets)
    # Check by trying to read entrypoint field from meta
    tendril = coglet.scope(coglet_id=c.coglet_id)
    status = tendril.get_status()
    files = tendril.list_files()
    if "main.md" in files or "main.py" in files:
        tendril.run(procs, capability_overrides={
            "me": None, "procs": None, "dir": None, "file": None,
            "discord": None, "channels": None, "secrets": None, "stdlib": None,
            "coglet_factory": None, "coglet": None,
        })

print("Init complete")
```

Note: The exact init.py content will need tuning — the handler subscriptions for discord-handle-message and newsfromthefront need multiple channels. The subscribe parameter only takes one channel. For multiple handlers, we need to create them after spawn. Check the existing `add_process` handler bindings and replicate them.

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_reboot.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add images/ tests/cogos/test_reboot.py
git commit -m "feat(cogos): add init process and boot script, remove static process declarations"
```

---

### Task 7: Full Verification

**Step 1: Run all tests**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/ tests/dashboard/ -v -x --ignore=tests/cogos/capabilities/test_web_search.py`
Expected: All pass

**Step 2: Reload and verify**

```bash
USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha reload -y
USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha process list
```
Expected: Only `init` process in RUNNABLE state

**Step 3: Test reboot**

```bash
USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha reboot -y
USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha process list
```
Expected: Fresh `init` process in RUNNABLE state

**Step 4: Commit if fixups needed**

```bash
git add -A && git commit -m "fix: address init/reboot verification fixups"
```
