# Executor Tags & Unified Dispatch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the `runner` field on processes with `required_tags`, rename executor `capabilities` to `executor_tags`, add `dispatch_type` to executors, and wire channel dispatch to actually deliver work to executor channels.

**Architecture:** Processes no longer know how they'll be executed — they just declare `required_tags`. Executors register with `executor_tags` and a `dispatch_type` ("channel" or "lambda"). The scheduler matches tags, then dispatches via the executor's dispatch_type. Channel dispatch sends a message to `system:executor:{id}`. Lambda dispatch invokes the Lambda function as before.

**Tech Stack:** Python (FastAPI, Pydantic), TypeScript (MCP channel server), PostgreSQL, SQLite (local repo)

---

### Task 1: Rename executor `capabilities` to `executor_tags` in the model

**Files:**
- Modify: `src/cogos/db/models/executor.py:24`

**Step 1: Update the Executor model field**

In `src/cogos/db/models/executor.py`, rename the field:

```python
# Line 24: change
capabilities: list[str] = Field(default_factory=list)
# to
executor_tags: list[str] = Field(default_factory=list)
```

**Step 2: Commit**

```bash
git add src/cogos/db/models/executor.py
git commit -m "refactor: rename Executor.capabilities to executor_tags"
```

---

### Task 2: Add `dispatch_type` to executor model and DB migration

**Files:**
- Modify: `src/cogos/db/models/executor.py:20-29`
- Modify: `src/cogos/db/migrations/020_executor_tables.sql`

**Step 1: Add dispatch_type field to Executor model**

In `src/cogos/db/models/executor.py`, add after the `executor_tags` field:

```python
dispatch_type: str = "channel"  # "channel" | "lambda"
```

**Step 2: Update the migration**

In `src/cogos/db/migrations/020_executor_tables.sql`, rename `capabilities` column to `executor_tags` and add `dispatch_type`:

```sql
CREATE TABLE IF NOT EXISTS cogos_executor (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    executor_id       TEXT NOT NULL,
    channel_type      TEXT NOT NULL DEFAULT 'claude-code',
    executor_tags     JSONB NOT NULL DEFAULT '[]',
    dispatch_type     TEXT NOT NULL DEFAULT 'channel',
    metadata          JSONB NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'idle'
                      CHECK (status IN ('idle', 'busy', 'stale', 'dead')),
    current_run_id    UUID,
    last_heartbeat_at TIMESTAMPTZ,
    registered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(executor_id)
);
```

**Step 3: Commit**

```bash
git add src/cogos/db/models/executor.py src/cogos/db/migrations/020_executor_tables.sql
git commit -m "feat: add dispatch_type to executor model and rename capabilities to executor_tags in migration"
```

---

### Task 3: Add `required_tags` to Process model, keep `runner` for now

We keep `runner` temporarily to avoid breaking everything at once. The scheduler will read `required_tags` when present, falling back to `runner`-based dispatch.

**Files:**
- Modify: `src/cogos/db/models/process.py:36`

**Step 1: Add required_tags field**

In `src/cogos/db/models/process.py`, add after the `runner` field (line 36):

```python
required_tags: list[str] = Field(default_factory=list)
```

**Step 2: Commit**

```bash
git add src/cogos/db/models/process.py
git commit -m "feat: add required_tags field to Process model"
```

---

### Task 4: Update RDS repository — executor CRUD with renamed fields

**Files:**
- Modify: `src/cogos/db/repository.py` (executor section, ~lines 2357-2469)

**Step 1: Update `_row_to_executor`**

```python
def _row_to_executor(self, row: dict) -> Executor:
    tags = row.get("executor_tags")
    if isinstance(tags, str):
        tags = json.loads(tags)
    meta = row.get("metadata")
    if isinstance(meta, str):
        meta = json.loads(meta)
    run_id = row.get("current_run_id")
    return Executor(
        id=UUID(row["id"]),
        executor_id=row["executor_id"],
        channel_type=row.get("channel_type", "claude-code"),
        executor_tags=tags or [],
        dispatch_type=row.get("dispatch_type", "channel"),
        metadata=meta or {},
        status=ExecutorStatus(row.get("status", "idle")),
        current_run_id=UUID(run_id) if run_id else None,
        last_heartbeat_at=self._ts(row, "last_heartbeat_at"),
        registered_at=self._ts(row, "registered_at"),
    )
```

**Step 2: Update `register_executor`**

Change all `capabilities` references to `executor_tags` and add `dispatch_type` in both UPDATE and INSERT SQL.

In the UPDATE:
```sql
SET channel_type = :channel_type,
    executor_tags = :executor_tags::jsonb,
    dispatch_type = :dispatch_type,
    metadata = :metadata::jsonb,
    ...
```

In the INSERT:
```sql
INSERT INTO cogos_executor
   (id, executor_id, channel_type, executor_tags, dispatch_type, metadata, status, last_heartbeat_at, registered_at)
   VALUES (:id, :executor_id, :channel_type, :executor_tags::jsonb, :dispatch_type, :metadata::jsonb, 'idle', now(), now())
```

Update params:
```python
self._param("executor_tags", executor.executor_tags),
self._param("dispatch_type", executor.dispatch_type),
```

**Step 3: Update `select_executor`**

Rename parameters from `required_caps`/`preferred_caps` to `required_tags`/`preferred_tags`:

```python
def select_executor(
    self,
    required_tags: list[str] | None = None,
    preferred_tags: list[str] | None = None,
) -> Executor | None:
    idle = self.list_executors(status=ExecutorStatus.IDLE)
    if not idle:
        return None

    candidates = idle
    if required_tags:
        req = set(required_tags)
        candidates = [e for e in candidates if req.issubset(set(e.executor_tags))]

    if not candidates:
        return None

    if preferred_tags:
        pref = set(preferred_tags)
        candidates.sort(key=lambda e: len(pref & set(e.executor_tags)), reverse=True)

    return candidates[0]
```

**Step 4: Commit**

```bash
git add src/cogos/db/repository.py
git commit -m "refactor: update RDS repository executor methods for executor_tags and dispatch_type"
```

---

### Task 5: Update local repository — executor methods with renamed fields

**Files:**
- Modify: `src/cogos/db/local_repository.py` (~lines 1500-1553)

**Step 1: Update `select_executor`**

Same rename as RDS: `required_caps`→`required_tags`, `preferred_caps`→`preferred_tags`, `e.capabilities`→`e.executor_tags`.

**Step 2: Commit**

```bash
git add src/cogos/db/local_repository.py
git commit -m "refactor: update local repository executor methods for executor_tags"
```

---

### Task 6: Update scheduler — use process `required_tags` and executor `dispatch_type`

**Files:**
- Modify: `src/cogos/capabilities/scheduler.py` (~lines 279-338)

**Step 1: Update `dispatch_channel` to read `required_tags` from the process**

Replace the runner_config/executor_filter extraction (lines 300-304) with:

```python
required_tags = proc.required_tags or []
```

Remove the `runner` check (lines 294-295) — processes no longer declare a runner.

**Step 2: Update parameter names in `select_executor` call**

```python
executor = self.repo.select_executor(
    required_tags=required_tags or None,
)
```

**Step 3: Rename `dispatch_channel` to `dispatch_to_executor`**

Since this now handles all dispatch types, rename the method. Update `ChannelDispatchResult` to just `ExecutorDispatchResult`.

**Step 4: Commit**

```bash
git add src/cogos/capabilities/scheduler.py
git commit -m "refactor: scheduler uses process.required_tags and executor.dispatch_type"
```

---

### Task 7: Update ingress — unified dispatch path

**Files:**
- Modify: `src/cogos/runtime/ingress.py`

**Step 1: Rewrite `dispatch_ready_processes`**

All processes now go through executor dispatch. The runner-based branching (lines 92-102) is replaced:

```python
def dispatch_ready_processes(
    repo,
    scheduler,
    lambda_client: Any,
    executor_function_name: str,
    process_ids: set[UUID],
    ecs_client: Any = None,
    ecs_cluster: str = "",
    ecs_task_definition: str = "",
) -> int:
    dispatched = 0

    for process_id in sorted(process_ids, key=str):
        proc = repo.get_process(process_id)
        if proc is None or proc.status != ProcessStatus.RUNNABLE:
            continue

        result = scheduler.dispatch_to_executor(process_id=str(process_id))
        if hasattr(result, "error"):
            logger.warning("Executor dispatch failed for %s: %s", process_id, result.error)
            continue

        executor = repo.get_executor(result.executor_id)
        if not executor:
            logger.error("Executor %s not found after dispatch", result.executor_id)
            continue

        payload = build_dispatch_event(repo, result)

        if executor.dispatch_type == "lambda":
            try:
                response = lambda_client.invoke(
                    FunctionName=executor_function_name,
                    InvocationType="Event",
                    Payload=json.dumps(payload),
                )
                if response.get("StatusCode") != 202:
                    raise RuntimeError(f"unexpected status {response.get('StatusCode')}")
                dispatched += 1
            except Exception as exc:
                repo.rollback_dispatch(
                    proc.id, UUID(result.run_id),
                    UUID(result.delivery_id) if getattr(result, 'delivery_id', None) else None,
                    error=str(exc),
                )
                logger.exception("Failed to invoke lambda for %s", proc.name)
        else:
            # Channel dispatch: send to executor's channel
            from cogos.db.models import ChannelMessage
            exec_ch = repo.get_channel_by_name(f"system:executor:{result.executor_id}")
            if exec_ch:
                repo.append_channel_message(ChannelMessage(
                    channel=exec_ch.id,
                    payload=payload,
                ))
                dispatched += 1
            else:
                logger.error("Executor channel not found for %s", result.executor_id)
                repo.rollback_dispatch(
                    proc.id, UUID(result.run_id), None,
                    error="executor channel not found",
                )

    return dispatched
```

**Step 2: Commit**

```bash
git add src/cogos/runtime/ingress.py
git commit -m "feat: unified dispatch — channel executors receive work via channel messages"
```

---

### Task 8: Update executor daemon and CLI

**Files:**
- Modify: `src/cogos/executor/daemon.py` (~lines 33, 40, 55-56)
- Modify: `src/cogos/cli/__main__.py` (~lines 1643, 1659)

**Step 1: Rename `capabilities` to `executor_tags` in ExecutorDaemon**

```python
def __init__(self, repo, executor_id, *, executor_tags=None, ...):
    self.executor_tags = executor_tags or ["python"]
    ...

def register(self):
    executor = Executor(
        executor_id=self.executor_id,
        channel_type="claude-code",
        executor_tags=self.executor_tags,
        dispatch_type="channel",
        ...
    )
```

**Step 2: Update CLI option**

```python
@click.option("--tags", "-t", default="python", help="Comma-separated executor tags")
```

Pass as `executor_tags=[t.strip() for t in tags.split(",")]`.

**Step 3: Commit**

```bash
git add src/cogos/executor/daemon.py src/cogos/cli/__main__.py
git commit -m "refactor: executor daemon uses executor_tags instead of capabilities"
```

---

### Task 9: Update dashboard API — executors router

**Files:**
- Modify: `src/dashboard/routers/executors.py` (~lines 20-68)

**Step 1: Update request/response models**

```python
class RegisterRequest(BaseModel):
    executor_id: str
    channel_type: str = "claude-code"
    executor_tags: list[str] = []
    dispatch_type: str = "channel"
    metadata: dict[str, Any] = {}

class ExecutorItem(BaseModel):
    id: str
    executor_id: str
    channel_type: str = "claude-code"
    executor_tags: list[str] = []
    dispatch_type: str = "channel"
    metadata: dict[str, Any] = {}
    status: str = "idle"
    current_run_id: str | None = None
    last_heartbeat_at: str | None = None
    registered_at: str | None = None
```

**Step 2: Update register_executor endpoint**

```python
executor = Executor(
    executor_id=body.executor_id,
    channel_type=body.channel_type,
    executor_tags=body.executor_tags,
    dispatch_type=body.dispatch_type,
    metadata=body.metadata,
)
```

**Step 3: Update list/get response mappings**

Change `capabilities=e.capabilities` to `executor_tags=e.executor_tags` and add `dispatch_type=e.dispatch_type`.

**Step 4: Commit**

```bash
git add src/dashboard/routers/executors.py
git commit -m "refactor: dashboard executor API uses executor_tags and dispatch_type"
```

---

### Task 10: Update dashboard API — processes router (add required_tags)

**Files:**
- Modify: `src/dashboard/routers/processes.py` (~lines 39-115, 134-170, 346-397)

**Step 1: Add `required_tags` to ProcessDetail, ProcessSummary, ProcessCreate, ProcessUpdate**

```python
# ProcessDetail (line 46): add
required_tags: list[str] = []

# ProcessSummary (line 30): add
required_tags: list[str] = []

# ProcessCreate (line 77): add
required_tags: list[str] = []

# ProcessUpdate (line 100): add
required_tags: list[str] | None = None
```

**Step 2: Update `_summary` and `_detail` to include required_tags**

```python
required_tags=p.required_tags,
```

**Step 3: Update `create_process` and `update_process` to handle required_tags**

In `create_process`:
```python
required_tags=body.required_tags,
```

In `update_process`:
```python
if body.required_tags is not None:
    p.required_tags = body.required_tags
```

**Step 4: Commit**

```bash
git add src/dashboard/routers/processes.py
git commit -m "feat: add required_tags to process API endpoints"
```

---

### Task 11: Update Claude Code channel server (TypeScript)

**Files:**
- Modify: `channels/claude-code/server.ts` (~lines 307-312)

**Step 1: Update registration payload**

```typescript
body: JSON.stringify({
    executor_id: EXECUTOR_ID,
    channel_type: "claude-code",
    executor_tags: ["claude-code"],
    dispatch_type: "channel",
    metadata: { mcp: true, hostname: hostname() },
}),
```

**Step 2: Commit**

```bash
git add channels/claude-code/server.ts
git commit -m "refactor: channel server registers with executor_tags instead of capabilities"
```

---

### Task 12: Update dashboard frontend — process form

**Files:**
- Modify: `dashboard/frontend/src/components/processes/ProcessesPanel.tsx` (~lines 42, 53-93, 113-135, 1808-1816, 2095-2119)
- Modify: `dashboard/frontend/src/lib/types.ts` (~line 20)

**Step 1: Update types.ts**

Add `required_tags: string[]` to `CogosProcess` interface. Keep `runner` for backwards compat display.

**Step 2: Update ProcessForm interface**

Replace `runner: string` with `required_tags: string[]`. Remove `RUNNERS` constant.

**Step 3: Update `EMPTY_FORM`**

Replace `runner: "lambda"` with `required_tags: []`.

**Step 4: Update `formFromProcess`**

Replace `runner: p.runner` with `required_tags: p.required_tags ?? []`.

**Step 5: Replace Runner IconButtonGroup with Required Tags input**

Replace the Runner toggle (lines 1808-1816) with a tags input:

```tsx
<div className="flex-1">
  <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Required Tags</label>
  <input
    className={INPUT_CLS}
    value={form.required_tags.join(", ")}
    onChange={(e) => onChange({
      ...form,
      required_tags: e.target.value.split(",").map(t => t.trim()).filter(Boolean),
    })}
    placeholder="e.g. claude-code, gpu"
  />
</div>
```

**Step 6: Update `handleSave`**

Replace `runner: form.runner` with `required_tags: form.required_tags`.

**Step 7: Commit**

```bash
git add dashboard/frontend/src/components/processes/ProcessesPanel.tsx dashboard/frontend/src/lib/types.ts
git commit -m "feat: replace runner toggle with required_tags input in process form"
```

---

### Task 13: Create io channels when dashboard creates a process

**Files:**
- Modify: `src/dashboard/routers/processes.py` (~lines 346-378)

**Step 1: After `repo.upsert_process(p)`, create io channels**

```python
repo.upsert_process(p)

# Create io channels for the process
from cogos.db.models import Channel, ChannelType, Handler
for stream in ("stdin", "stdout", "stderr"):
    ch = Channel(
        name=f"io:{stream}:{body.name}",
        owner_process=p.id,
        channel_type=ChannelType.NAMED,
    )
    repo.upsert_channel(ch)

# Subscribe process to its stdin channel so messages wake it
stdin_ch = repo.get_channel_by_name(f"io:stdin:{body.name}")
if stdin_ch:
    repo.create_handler(Handler(process=p.id, channel=stdin_ch.id, enabled=True))
```

**Step 2: Commit**

```bash
git add src/dashboard/routers/processes.py
git commit -m "feat: create io channels and stdin handler when creating process via dashboard"
```

---

### Task 14: Update tests

**Files:**
- Modify: `tests/cogos/test_channel_dispatch.py`

**Step 1: Update test helpers**

```python
def _make_channel_process(repo, *, name="channel-proc", status=ProcessStatus.RUNNABLE,
                          required_tags=None, metadata=None) -> Process:
    p = Process(
        name=name,
        mode=ProcessMode.DAEMON,
        status=status,
        required_tags=required_tags or [],
        priority=50.0,
        metadata=metadata or {},
    )
    repo.upsert_process(p)
    return p


def _register_executor(repo, *, executor_id="exec-1", executor_tags=None,
                        dispatch_type="channel") -> Executor:
    e = Executor(
        executor_id=executor_id,
        executor_tags=executor_tags or ["claude-code", "git"],
        dispatch_type=dispatch_type,
    )
    repo.register_executor(e)
    return e
```

**Step 2: Update test methods**

- Rename `dispatch_channel` calls to `dispatch_to_executor`
- Remove `test_dispatch_wrong_runner_rejected` (no longer relevant)
- Update capability filter tests to use `required_tags` on process instead of metadata:

```python
def test_dispatch_with_tag_filter(self, repo, scheduler):
    proc = _make_channel_process(repo, required_tags=["claude-code", "gpu"])
    _register_executor(repo, executor_id="exec-cpu", executor_tags=["claude-code", "git"])
    _register_executor(repo, executor_id="exec-gpu", executor_tags=["claude-code", "git", "gpu"])

    result = scheduler.dispatch_to_executor(process_id=str(proc.id))

    assert isinstance(result, ExecutorDispatchResult)
    assert result.executor_id == "exec-gpu"
```

**Step 3: Run tests**

```bash
pytest tests/cogos/test_channel_dispatch.py -v
```

**Step 4: Commit**

```bash
git add tests/cogos/test_channel_dispatch.py
git commit -m "test: update channel dispatch tests for executor_tags and required_tags"
```

---

### Task 15: Seed a lambda pool executor for backward compatibility

**Files:**
- Modify: `src/cogtainer/lambdas/dispatcher/handler.py` (~line 37)

**Step 1: On dispatcher startup, ensure a lambda pool executor exists**

Add after line 47 (`scheduler = SchedulerCapability(...)`):

```python
# Ensure a lambda pool executor is registered for backward compat
from cogos.db.models.executor import Executor
lambda_executor = Executor(
    executor_id="lambda-pool",
    channel_type="lambda",
    executor_tags=["lambda", "python"],
    dispatch_type="lambda",
    metadata={"pool": True},
)
repo.register_executor(lambda_executor)
```

This ensures processes with `required_tags: ["lambda"]` (migrated from `runner: "lambda"`) still get dispatched.

**Step 2: Commit**

```bash
git add src/cogtainer/lambdas/dispatcher/handler.py
git commit -m "feat: seed lambda pool executor on dispatcher startup"
```

---

### Task 16: Migrate existing processes — backfill `required_tags` from `runner`

**Files:**
- Modify: `src/cogos/capabilities/scheduler.py` (in `dispatch_to_executor`)

**Step 1: Add fallback logic**

In `dispatch_to_executor`, if `proc.required_tags` is empty, fall back to the old `runner` field:

```python
required_tags = proc.required_tags
if not required_tags and proc.runner:
    # Backward compat: map old runner to tag
    required_tags = [proc.runner]
```

This keeps old processes working during migration.

**Step 2: Commit**

```bash
git add src/cogos/capabilities/scheduler.py
git commit -m "feat: fallback to runner field for processes without required_tags"
```

---

### Task 17: Clean up remaining `.runner` references

**Files:**
- Modify: `src/cogos/capabilities/scheduler.py` — remove `runner` from `DispatchResult`
- Modify: `src/cogos/capabilities/scheduler.py` — remove `runner` from `ChannelDispatchResult` (now `ExecutorDispatchResult`)
- Modify: `src/dashboard/routers/processes.py` — keep `runner` in API response for display but mark deprecated
- Modify: `src/cogos/shell/commands/procs.py` — display `required_tags` instead of `runner`
- Modify: `src/cogos/image/snapshot.py` — include `required_tags`

This task is intentionally deferred — the backward-compat fallback in Task 16 means we can clean up `runner` references incrementally without breaking anything.

**Step 1: Update `DispatchResult` and related models**

Remove `runner: str` field, add `executor_id: str` and `dispatch_type: str`.

**Step 2: Commit**

```bash
git add src/cogos/capabilities/scheduler.py src/cogos/shell/commands/procs.py src/cogos/image/snapshot.py
git commit -m "refactor: clean up runner references in scheduler and display code"
```

---

## Notes

- **No data migration needed:** The backward-compat fallback (Task 16) reads `runner` when `required_tags` is empty, so existing processes keep working without a data migration.
- **The `runner` field is NOT removed** from the Process model in this plan — it's kept for backward compatibility. A follow-up PR can remove it once all processes have been migrated to `required_tags`.
- **Lambda pool executor concurrency:** The lambda pool executor stays IDLE permanently (lambda invocations are fire-and-forget), so multiple processes can match it simultaneously. The `select_executor` method needs no special handling since lambda invocations don't consume executor slots.
- **ECS scale-up** is out of scope for this plan — ECS tasks that register as channel executors will be handled separately.
