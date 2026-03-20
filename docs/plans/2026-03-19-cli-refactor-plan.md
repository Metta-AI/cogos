# CLI Refactor: Remove Cogent Name from Argv

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `cogos` the sole CLI entry point, removing the positional cogent-name argument in favor of `--cogent/-c` / `COGENT_ID` env / config default.

**Architecture:** The `cogos` group in `src/cogos/cli/__main__.py` already has the `--cogent/-c` option with env/config fallback. We promote it to the sole entry point, move `memory` and `shell` commands into it, replace `--local` with `--executor`, and delete the old `src/cli/__main__.py` router, `src/run/` (ECS interaction), and `src/cli/dashboard.py` (duplicate of cogos dashboard).

**Tech Stack:** Click CLI, Python, pyproject.toml entry points

---

### Task 1: Update pyproject.toml entry point and package list

**Files:**
- Modify: `pyproject.toml:59,69`

**Step 1: Update entry point and packages**

Change the `cogos` entry point from `cli.__main__:entry` to `cogos.cli.__main__:entry`, and remove `src/run` and `src/cogtainer` from the packages list (cogtainer CDK was already deleted, only update_cli.py and DB remain):

```toml
# line 59: change entry point
cogos = "cogos.cli.__main__:entry"

# line 69: remove "src/run" from packages (keep src/cogtainer since db/models still used)
packages = ["src/cli", "src/cogents", "src/cogos", "src/cogtainer", "src/dashboard", "src/memory", "src/polis"]
```

**Step 2: Verify**

Run: `cd /Users/daveey/code/cogents/cogents.4 && uv run cogos --help`
Expected: Shows the cogos help with `--cogent/-c` option and subcommands (process, file, image, etc.)

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "refactor: point cogos entry to cogos.cli.__main__"
```

---

### Task 2: Add memory subcommand to cogos CLI

**Files:**
- Modify: `src/cogos/cli/__main__.py` (add import and registration near other command registrations)

**Step 1: Add memory command group**

At the bottom of `src/cogos/cli/__main__.py`, before the `entry()` function (around line 1420), add:

```python
# Memory management CLI
from memory.cli import memory  # noqa: E402

cogos.add_command(memory)
```

**Step 2: Verify**

Run: `uv run cogos --help`
Expected: `memory` appears in the command list.

Run: `uv run cogos memory --help`
Expected: Shows memory subcommands (status, list, get, history, put, etc.)

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "feat: add memory subcommand to cogos CLI"
```

---

### Task 3: Add shell subcommand to cogos CLI

**Files:**
- Modify: `src/cogos/cli/__main__.py`

**Step 1: Add shell command**

At the bottom of `src/cogos/cli/__main__.py`, before the `entry()` function, add:

```python
@cogos.command("shell")
@click.pass_context
def shell_cmd(ctx: click.Context):
    """Interactive CogOS shell."""
    from cogos.shell import CogentShell

    cogent_name = ctx.obj.get("cogent_name")
    if not cogent_name:
        raise click.UsageError("No cogent specified. Use --cogent/-c, set COGENT_ID, or set default_cogent in ~/.cogos/config.yml")
    CogentShell(cogent_name).run()
```

**Step 2: Verify**

Run: `uv run cogos --help`
Expected: `shell` appears in the command list.

Run: `uv run cogos shell --help`
Expected: Shows shell help text.

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "feat: add shell subcommand to cogos CLI"
```

---

### Task 4: Replace --local with --executor on process run

**Files:**
- Modify: `src/cogos/cli/__main__.py:420-469`

**Step 1: Update the process_run command**

Replace the `process_run` function. Change `--local` flag to `--executor` option that defaults to the process's `runner` field. The three modes:
- `lambda`: mark process RUNNABLE for Lambda scheduler (current default behavior)
- `ecs`: (future, same as lambda for now — mark RUNNABLE)
- `local`: run locally via Bedrock (current `--local` behavior)

```python
@process.command("run")
@click.argument("name")
@click.option("--executor", "executor_override", type=click.Choice(["lambda", "ecs", "local"]),
              default=None, help="Executor backend (default: from process runner field)")
@click.option("--event", default=None, help="JSON event data (e.g. '{\"channel_name\":\"system:tick:hour\"}')")
def process_run(name: str, executor_override: str | None, event: str | None):
    """Trigger a process to run."""
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Process not found: {name}")
        return

    executor = executor_override or p.runner

    if executor == "local":
        from cogos.db.models import ProcessStatus, Run, RunStatus
        from cogos.executor.handler import get_config
        from cogos.runtime.local import run_and_complete

        config = get_config()
        repo.update_process_status(p.id, ProcessStatus.RUNNING)

        run = Run(process=p.id, status=RunStatus.RUNNING)
        repo.create_run(run)
        click.echo(f"Starting local run {run.id} for {name}...")

        bedrock = _bedrock_client()
        event_data = json.loads(event) if event else {}
        try:
            run = run_and_complete(p, event_data, run, config, repo, bedrock_client=bedrock)
        except Exception as exc:
            import traceback
            click.echo(f"Exception during execution:\n{traceback.format_exc()}")
            run.status = RunStatus.FAILED
            run.error = str(exc)

        click.echo(f"  Run status: {run.status}")
        if run.status == RunStatus.COMPLETED:
            click.echo(f"Run completed in {run.duration_ms or 0}ms")
            click.echo(f"  Tokens: {run.tokens_in} in, {run.tokens_out} out")
            if run.result:
                click.echo(f"  Output: {json.dumps(run.result)[:500]}")
        else:
            db_run = repo.get_run(run.id)
            error = (db_run.error if db_run else None) or run.error or "(unknown)"
            click.echo(f"Run failed: {error}")
    else:
        # lambda or ecs: mark as runnable for scheduler
        from cogos.db.models import ProcessStatus
        repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
        click.echo(f"Process {name} marked RUNNABLE (executor={executor})")
```

**Step 2: Verify**

Run: `uv run cogos process run --help`
Expected: Shows `--executor [lambda|ecs|local]` option, no `--local` flag.

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "refactor: replace --local with --executor on process run"
```

---

### Task 5: Remove run-local command from cogos CLI

**Files:**
- Modify: `src/cogos/cli/__main__.py:1092-1119` — delete the `run_local` command

**Step 1: Delete the run-local command**

Remove the entire `run_local` function and its decorator block (lines 1092-1119 approximately):

```python
# DELETE THIS ENTIRE BLOCK:
@cogos.command("run-local")
@click.option("--poll-interval", ...)
...
def run_local(ctx, poll_interval, once):
    ...
```

**Step 2: Verify**

Run: `uv run cogos --help`
Expected: `run-local` no longer appears in command list.

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "refactor: remove run-local command (use process run --executor local)"
```

---

### Task 6: Update get_cogent_name() utility

**Files:**
- Modify: `src/cli/__init__.py:8-14`

**Step 1: Update to check both key names**

The cogos group stores the cogent as `cogent_name` in ctx.obj, but `get_cogent_name()` looks for `cogent_id`. Update it to check both:

```python
def get_cogent_name(ctx: click.Context) -> str:
    """Return the cogent identifier from the root context."""
    obj = ctx.find_root().obj
    name = (obj.get("cogent_name") or obj.get("cogent_id")) if obj else None
    if not name:
        raise click.UsageError("No cogent specified. Use --cogent/-c, set COGENT_ID, or set default_cogent in ~/.cogos/config.yml")
    return name
```

**Step 2: Verify**

Run: `uv run python -c "from cli import get_cogent_name; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add src/cli/__init__.py
git commit -m "refactor: get_cogent_name checks both cogent_name and cogent_id keys"
```

---

### Task 7: Delete src/run/ (ECS interaction CLI)

**Files:**
- Delete: `src/run/cli.py`
- Delete: `src/run/__init__.py` (if exists)

**Step 1: Check what files exist in src/run/**

Run: `ls src/run/`

**Step 2: Delete the directory**

Run: `rm -rf src/run/`

**Step 3: Remove run import from old entry point**

This will be handled in Task 8 when we gut `src/cli/__main__.py`.

**Step 4: Verify**

Run: `uv run cogos --help`
Expected: Works without errors, no `run` at top level (the cogos group has its own `run` subgroup for run history).

**Step 5: Commit**

```bash
git add -A src/run/
git commit -m "refactor: remove ECS interaction CLI (src/run/)"
```

---

### Task 8: Gut src/cli/__main__.py

**Files:**
- Modify: `src/cli/__main__.py` — remove all command registrations, keep only as a minimal backward-compat re-export if needed

**Step 1: Replace src/cli/__main__.py**

Since the entry point now goes directly to `cogos.cli.__main__:entry`, replace `src/cli/__main__.py` with a minimal stub that re-exports for any remaining imports:

```python
"""Legacy CLI entry point — redirects to cogos.cli.__main__."""

# Backward compat: some modules import from cli.__main__
from cogos.cli.__main__ import cogos as main, entry  # noqa: F401
```

**Step 2: Verify**

Run: `uv run cogos --help`
Expected: Works, shows cogos commands.

**Step 3: Commit**

```bash
git add src/cli/__main__.py
git commit -m "refactor: gut cli.__main__ — entry point now in cogos.cli.__main__"
```

---

### Task 9: Delete src/cli/dashboard.py (duplicate)

**Files:**
- Delete: `src/cli/dashboard.py`

The cogos CLI already has its own dashboard group (`src/cogos/cli/__main__.py:1186`). The old `src/cli/dashboard.py` was the top-level `cogos <name> dashboard` which is now redundant.

**Step 1: Delete the file**

Run: `rm src/cli/dashboard.py`

**Step 2: Verify**

Run: `uv run cogos dashboard --help`
Expected: Shows dashboard subcommands (start, stop, reload) from the cogos CLI.

**Step 3: Commit**

```bash
git add src/cli/dashboard.py
git commit -m "refactor: remove duplicate dashboard CLI (use cogos dashboard)"
```

---

### Task 10: Update tests

**Files:**
- Delete: `tests/cli/test_main.py` (tests `_preprocess_argv` which no longer exists)
- Delete: `tests/cli/test_shell_entry.py` (tests `_COMMANDS` set which no longer exists)
- Optionally update: `tests/cli/test_io_cli.py` and `tests/cli/test_local_dev.py` if they import from deleted modules

**Step 1: Check test files for broken imports**

Run: `head -20 tests/cli/test_io_cli.py tests/cli/test_local_dev.py`

**Step 2: Delete broken tests**

```bash
rm tests/cli/test_main.py tests/cli/test_shell_entry.py
```

**Step 3: Fix any remaining test imports if needed**

Check `tests/cli/test_local_dev.py` — it likely tests `cli.local_dev` which still exists, so it should be fine.

**Step 4: Run tests**

Run: `uv run pytest tests/cli/ -v`
Expected: All remaining tests pass.

**Step 5: Commit**

```bash
git add tests/cli/
git commit -m "test: remove obsolete CLI tests for deleted entry point"
```

---

### Task 11: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: All tests pass.

**Step 2: Smoke test the CLI**

Run: `uv run cogos --help`
Expected: Shows all commands: process, handler, file, capability, channel, run, image, io, dashboard, memory, shell, status, wipe, reload, reboot

Run: `uv run cogos process --help`
Expected: Shows process subcommands including `run` with `--executor` option.

Run: `COGENT_ID=test cogos process run --help`
Expected: Shows `--executor [lambda|ecs|local]`.

**Step 3: Final commit if any fixups needed**

```bash
git add -A && git commit -m "refactor: CLI refactor complete — cogos is sole entry point"
```
