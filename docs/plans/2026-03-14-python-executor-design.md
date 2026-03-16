# Python Executor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an `executor` field to Process so processes can run raw Python directly in the sandbox, skipping the LLM.

**Architecture:** New `executor` field on Process model (default `"llm"`, also `"python"`). `execute_process()` branches: python processes resolve content via ContextEngine, run it in SandboxExecutor with capability proxies, capture stdout as result. All run lifecycle (create/complete/fail, retries, alerts) stays the same.

**Tech Stack:** Python, Pydantic, PostgreSQL (Aurora Data API), pytest

---

### Task 1: Add `executor` field to Process model

**Files:**
- Modify: `src/cogos/db/models/process.py:35` (add field after `runner`)

**Step 1: Add the field**

In `src/cogos/db/models/process.py`, add after line 35 (`runner: str = "lambda"`):

```python
executor: str = "llm"  # "llm" | "python"
```

**Step 2: Run existing tests to verify no breakage**

Run: `pytest tests/cogos/test_executor_handler.py -x -q`
Expected: All existing tests PASS (field defaults to `"llm"`)

**Step 3: Commit**

```bash
git add src/cogos/db/models/process.py
git commit -m "feat(cogos): add executor field to Process model"
```

---

### Task 2: Add DB migration for executor column

**Files:**
- Create: `src/cogos/db/migrations/011_process_executor.sql`

**Step 1: Write the migration**

Create `src/cogos/db/migrations/011_process_executor.sql`:

```sql
ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS executor TEXT NOT NULL DEFAULT 'llm';
```

**Step 2: Commit**

```bash
git add src/cogos/db/migrations/011_process_executor.sql
git commit -m "feat(cogos): add executor column migration"
```

---

### Task 3: Wire executor field through repository layer

**Files:**
- Modify: `src/cogos/db/repository.py:183-225` (upsert_process SQL and params)
- Modify: `src/cogos/db/repository.py:298-325` (_process_from_row)

**Step 1: Add executor to upsert_process SQL**

In `src/cogos/db/repository.py`, the `upsert_process` method has an INSERT statement. Add `executor` to the column list, VALUES list, and ON CONFLICT SET clause.

In the column list (line ~184), add `executor` after `runner`:
```
runner, executor,
```

In the VALUES list (line ~189), add `:executor` after `:runner`:
```
:runner, :executor,
```

In the ON CONFLICT SET clause (line ~196), add after `runner = EXCLUDED.runner`:
```
executor = EXCLUDED.executor,
```

In the params list (line ~215), add after `self._param("runner", p.runner)`:
```python
self._param("executor", p.executor),
```

**Step 2: Add executor to _process_from_row**

In `_process_from_row` (line ~308), add after `runner=row.get("runner", "lambda")`:
```python
executor=row.get("executor", "llm"),
```

**Step 3: Run existing tests**

Run: `pytest tests/cogos/test_executor_handler.py -x -q`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/db/repository.py
git commit -m "feat(cogos): wire executor field through repository layer"
```

---

### Task 4: Wire executor through image spec and apply

**Files:**
- Modify: `src/cogos/image/spec.py:49-60` (add_process function)
- Modify: `src/cogos/image/apply.py:119-129` (Process construction)

**Step 1: Add executor kwarg to add_process in spec.py**

In `src/cogos/image/spec.py`, modify `add_process` (line 49) to accept `executor="llm"` and include it in the dict:

```python
def add_process(name, *, mode="one_shot", content="",
                runner="lambda", executor="llm", model=None, priority=0.0,
                capabilities=None, handlers=None,
                metadata=None, idle_timeout_ms=None):
    spec.processes.append({
        "name": name, "mode": mode, "content": content,
        "runner": runner, "executor": executor, "model": model,
        "priority": priority, "capabilities": capabilities or [],
        "handlers": handlers or [],
        "metadata": metadata or {},
        "idle_timeout_ms": idle_timeout_ms,
    })
```

**Step 2: Read executor in apply.py**

In `src/cogos/image/apply.py`, in the Process construction (line ~119), add after `runner=proc_dict.get("runner", "lambda")`:

```python
executor=proc_dict.get("executor", "llm"),
```

**Step 3: Run existing image tests**

Run: `pytest tests/cogos/test_image_apply.py -x -q`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/image/spec.py src/cogos/image/apply.py
git commit -m "feat(cogos): wire executor through image spec and apply"
```

---

### Task 5: Write failing test for python executor

**Files:**
- Modify: `tests/cogos/test_executor_handler.py`

**Step 1: Write the test**

Add to `tests/cogos/test_executor_handler.py`:

```python
def test_python_executor_runs_code_directly(monkeypatch, tmp_path):
    """Python executor resolves content and runs it in sandbox — no Bedrock."""
    repo = _repo(tmp_path)

    # Set up a file capability so the process can use it
    cap = Capability(name="files/dir", handler="cogos.capabilities.file_cap:FileCapability", description="files")
    repo.upsert_capability(cap)

    process = Process(
        name="py-proc",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="print('hello from python')",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    repo.create_process_capability(ProcessCapability(process=process.id, capability=cap.id, name="files"))

    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process, {"process_id": str(process.id)}, run, config, repo,
    )

    assert result_run.result == "hello from python"
    assert result_run.tokens_in == 0
    assert result_run.tokens_out == 0
```

**Step 2: Run to verify it fails**

Run: `pytest tests/cogos/test_executor_handler.py::test_python_executor_runs_code_directly -x -v`
Expected: FAIL (execute_process still tries to call Bedrock for all processes)

**Step 3: Commit**

```bash
git add tests/cogos/test_executor_handler.py
git commit -m "test(cogos): add failing test for python executor"
```

---

### Task 6: Implement python executor path in execute_process

**Files:**
- Modify: `src/cogos/executor/handler.py:271-300`

**Step 1: Add python executor branch**

In `src/cogos/executor/handler.py`, at the top of `execute_process()` (after line 279), add a branch that short-circuits for python executor processes:

```python
def execute_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: ExecutorConfig,
    repo: Repository,
    *,
    bedrock_client: Any | None = None,
) -> Run:
    """Execute process via Bedrock converse API or direct Python execution."""
    if process.executor == "python":
        return _execute_python_process(process, event_data, run, config, repo)

    # ... existing LLM code unchanged ...
```

**Step 2: Implement _execute_python_process**

Add a new function before `execute_process` or after it (before the helper functions):

```python
def _execute_python_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: ExecutorConfig,
    repo: Repository,
) -> Run:
    """Execute process by running resolved content as Python in the sandbox."""
    from cogos.files.context_engine import ContextEngine
    from cogos.files.store import FileStore

    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)
    code = ctx.generate_full_prompt(process)

    if not code:
        run.result = "(no content to execute)"
        return run

    # Set up sandbox with capability proxies — same as LLM path
    vt = VariableTable()
    _setup_capability_proxies(vt, process, repo, run_id=run.id)

    # Inject event payload as a variable
    vt.set("event", event_data)

    sandbox = SandboxExecutor(vt)
    result = sandbox.execute(code)

    run.result = result
    run.tokens_in = 0
    run.tokens_out = 0
    run.scope_log = sandbox.scope_log
    return run
```

**Step 3: Run the test**

Run: `pytest tests/cogos/test_executor_handler.py::test_python_executor_runs_code_directly -x -v`
Expected: PASS

**Step 4: Run all executor tests**

Run: `pytest tests/cogos/test_executor_handler.py -x -q`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/cogos/executor/handler.py
git commit -m "feat(cogos): implement python executor path in execute_process"
```

---

### Task 7: Test python executor with event payload and file refs

**Files:**
- Modify: `tests/cogos/test_executor_handler.py`

**Step 1: Write test for event payload access**

```python
def test_python_executor_receives_event_payload(monkeypatch, tmp_path):
    """Python executor can access the triggering event via `event` variable."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-event",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="print(event.get('payload', {}).get('msg', 'none'))",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process,
        {"process_id": str(process.id), "payload": {"msg": "hi"}},
        run, config, repo,
    )

    assert result_run.result == "hi"
```

**Step 2: Write test for content file ref resolution**

```python
def test_python_executor_resolves_file_refs(monkeypatch, tmp_path):
    """Python executor resolves @{...} refs in content before executing."""
    repo = _repo(tmp_path)
    file_store = FileStore(repo)
    file_store.write("apps/greet/run.py", "print('resolved')", source="image")

    process = Process(
        name="py-ref",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="@{apps/greet/run.py}",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process,
        {"process_id": str(process.id)},
        run, config, repo,
    )

    assert result_run.result == "resolved"
```

**Step 3: Run tests**

Run: `pytest tests/cogos/test_executor_handler.py::test_python_executor_receives_event_payload tests/cogos/test_executor_handler.py::test_python_executor_resolves_file_refs -x -v`
Expected: PASS

**Step 4: Commit**

```bash
git add tests/cogos/test_executor_handler.py
git commit -m "test(cogos): add python executor event payload and file ref tests"
```

---

### Task 8: Test python executor error handling via full handler()

**Files:**
- Modify: `tests/cogos/test_executor_handler.py`

**Step 1: Write test for python executor errors going through run lifecycle**

```python
def test_python_executor_error_captured_in_run(monkeypatch, tmp_path):
    """Python executor errors are captured and the run is marked FAILED."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-err",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="raise ValueError('boom')",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    # The sandbox catches exceptions and returns traceback as output — it doesn't raise.
    result_run = executor_handler.execute_process(
        process,
        {"process_id": str(process.id)},
        run, config, repo,
    )

    assert "ValueError" in result_run.result
    assert "boom" in result_run.result
```

**Step 2: Run test**

Run: `pytest tests/cogos/test_executor_handler.py::test_python_executor_error_captured_in_run -x -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `pytest tests/cogos/test_executor_handler.py -x -q`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/cogos/test_executor_handler.py
git commit -m "test(cogos): add python executor error handling test"
```

---

### Task 9: Test image spec and apply with executor field

**Files:**
- Modify: `tests/cogos/test_image_apply.py` or `tests/cogos/test_image_snapshot.py`

**Step 1: Write test that add_process with executor="python" roundtrips**

Find the existing image spec/apply test file and add a test that creates an image with a python executor process and verifies it applies correctly:

```python
def test_image_python_executor_process(tmp_path):
    """add_process with executor='python' creates a process with executor set."""
    from cogos.image.spec import load_image

    app_dir = tmp_path / "test_image" / "apps" / "myapp"
    init_dir = app_dir / "init"
    init_dir.mkdir(parents=True)
    (init_dir / "processes.py").write_text(
        'add_process("my-py", executor="python", content="print(1)")'
    )
    # Also need the top-level structure
    top_init = tmp_path / "test_image" / "init"
    top_init.mkdir(parents=True)

    spec = load_image(tmp_path / "test_image")
    assert len(spec.processes) == 1
    assert spec.processes[0]["executor"] == "python"
    assert spec.processes[0]["content"] == "print(1)"
```

**Step 2: Run test**

Run: `pytest tests/cogos/test_image_apply.py -x -q` (or whichever file it goes in)
Expected: PASS

**Step 3: Run all tests**

Run: `pytest tests/ -x -q --timeout=30`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/
git commit -m "test(cogos): verify executor field roundtrips through image spec"
```
