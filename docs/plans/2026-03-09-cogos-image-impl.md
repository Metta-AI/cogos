# CogOS Image System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded `cogos bootstrap` with an image-based boot/snapshot/list system.

**Architecture:** `ImageSpec` dataclass holds pure data. `load_image()` exec's Python scripts in `init/` with injected builder functions. `apply_image()` upserts into DB via existing repo/FileStore. `snapshot_image()` reads DB and generates Python source files. CLI adds `image` subgroup with `boot`, `snapshot`, `list` commands.

**Tech Stack:** Python, Pydantic models, Click CLI, existing `Repository`/`LocalRepository`/`FileStore`

**Design doc:** `src/cogos/image/design.md`

---

### Task 1: ImageSpec and load_image

**Files:**
- Create: `src/cogos/image/__init__.py`
- Create: `src/cogos/image/spec.py`
- Create: `tests/cogos/test_image_spec.py`

**Step 1: Write the test**

```python
# tests/cogos/test_image_spec.py
import tempfile
from pathlib import Path

from cogos.image.spec import ImageSpec, load_image


def _write_image(tmp: Path) -> Path:
    """Create a minimal test image directory."""
    init = tmp / "init"
    init.mkdir(parents=True)

    (init / "capabilities.py").write_text(
        'add_capability("files", handler="cogos.capabilities.files.FilesCapability", description="File store")\n'
    )
    (init / "resources.py").write_text(
        'add_resource("lambda_slots", type="pool", capacity=5)\n'
    )
    (init / "processes.py").write_text(
        'add_process("scheduler", mode="daemon", priority=100.0, capabilities=["files"], handlers=["scheduler:tick"])\n'
    )
    (init / "cron.py").write_text(
        'add_cron("* * * * *", event_type="scheduler:tick")\n'
    )

    files = tmp / "files" / "cogos"
    files.mkdir(parents=True)
    (files / "scheduler.md").write_text("You are the scheduler.")

    return tmp


def test_load_image_parses_all_sections():
    with tempfile.TemporaryDirectory() as td:
        img_dir = _write_image(Path(td))
        spec = load_image(img_dir)

    assert len(spec.capabilities) == 1
    assert spec.capabilities[0]["name"] == "files"
    assert spec.capabilities[0]["handler"] == "cogos.capabilities.files.FilesCapability"

    assert len(spec.resources) == 1
    assert spec.resources[0]["name"] == "lambda_slots"
    assert spec.resources[0]["capacity"] == 5

    assert len(spec.processes) == 1
    assert spec.processes[0]["name"] == "scheduler"
    assert spec.processes[0]["capabilities"] == ["files"]
    assert spec.processes[0]["handlers"] == ["scheduler:tick"]

    assert len(spec.cron_rules) == 1
    assert spec.cron_rules[0]["event_type"] == "scheduler:tick"

    assert spec.files["cogos/scheduler.md"] == "You are the scheduler."


def test_load_image_no_init_dir():
    with tempfile.TemporaryDirectory() as td:
        spec = load_image(Path(td))
    assert spec.capabilities == []
    assert spec.files == {}


def test_load_image_no_files_dir():
    with tempfile.TemporaryDirectory() as td:
        init = Path(td) / "init"
        init.mkdir()
        (init / "capabilities.py").write_text(
            'add_capability("test", handler="mod.Test")\n'
        )
        spec = load_image(Path(td))
    assert len(spec.capabilities) == 1
    assert spec.files == {}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_image_spec.py -v`
Expected: FAIL (module not found)

**Step 3: Implement ImageSpec and load_image**

Create `src/cogos/image/__init__.py`:
```python
```

Create `src/cogos/image/spec.py`:
```python
"""ImageSpec and loader — pure data representation of a CogOS image."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImageSpec:
    capabilities: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    processes: list[dict] = field(default_factory=list)
    cron_rules: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)


def load_image(image_dir: Path) -> ImageSpec:
    """Load an image from a directory by exec'ing init/*.py and walking files/."""
    spec = ImageSpec()

    def add_capability(name, *, handler, description="", instructions="",
                       input_schema=None, output_schema=None,
                       iam_role_arn=None, metadata=None):
        spec.capabilities.append({
            "name": name, "handler": handler, "description": description,
            "instructions": instructions, "input_schema": input_schema,
            "output_schema": output_schema, "iam_role_arn": iam_role_arn,
            "metadata": metadata,
        })

    def add_resource(name, *, type, capacity, metadata=None):
        spec.resources.append({
            "name": name, "resource_type": type, "capacity": capacity,
            "metadata": metadata or {},
        })

    def add_process(name, *, mode="one_shot", content="", code_key=None,
                    runner="lambda", model=None, priority=0.0,
                    capabilities=None, handlers=None, metadata=None):
        spec.processes.append({
            "name": name, "mode": mode, "content": content,
            "code_key": code_key, "runner": runner, "model": model,
            "priority": priority, "capabilities": capabilities or [],
            "handlers": handlers or [], "metadata": metadata or {},
        })

    def add_cron(expression, *, event_type, payload=None, enabled=True):
        spec.cron_rules.append({
            "expression": expression, "event_type": event_type,
            "payload": payload or {}, "enabled": enabled,
        })

    builtins = {
        "add_capability": add_capability,
        "add_resource": add_resource,
        "add_process": add_process,
        "add_cron": add_cron,
    }

    init_dir = image_dir / "init"
    if init_dir.is_dir():
        for py in sorted(init_dir.glob("*.py")):
            exec(compile(py.read_text(), str(py), "exec"), builtins.copy())

    files_dir = image_dir / "files"
    if files_dir.is_dir():
        for f in sorted(files_dir.rglob("*")):
            if f.is_file():
                key = str(f.relative_to(files_dir))
                spec.files[key] = f.read_text()

    return spec
```

**Step 4: Run tests**

Run: `python -m pytest tests/cogos/test_image_spec.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/ tests/cogos/test_image_spec.py
git commit -m "feat(cogos): add ImageSpec and load_image for image boot system"
```

---

### Task 2: apply_image

**Files:**
- Create: `src/cogos/image/apply.py`
- Create: `tests/cogos/test_image_apply.py`

**Step 1: Write the test**

```python
# tests/cogos/test_image_apply.py
from cogos.db.local_repository import LocalRepository
from cogos.image.spec import ImageSpec
from cogos.image.apply import apply_image


def _make_spec() -> ImageSpec:
    return ImageSpec(
        capabilities=[
            {"name": "files", "handler": "cogos.capabilities.files.FilesCapability",
             "description": "File store", "instructions": "", "input_schema": None,
             "output_schema": None, "iam_role_arn": None, "metadata": None},
        ],
        resources=[],
        processes=[
            {"name": "scheduler", "mode": "daemon", "content": "scheduler daemon",
             "code_key": "cogos/scheduler", "runner": "lambda", "model": None,
             "priority": 100.0, "capabilities": ["files"],
             "handlers": ["scheduler:tick"], "metadata": {}},
        ],
        cron_rules=[],
        files={"cogos/scheduler": "You are the scheduler."},
    )


def test_apply_creates_capabilities(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    caps = repo.list_capabilities()
    assert len(caps) == 1
    assert caps[0].name == "files"


def test_apply_creates_files(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    f = repo.get_file_by_key("cogos/scheduler")
    assert f is not None
    fv = repo.get_active_file_version(f.id)
    assert fv.content == "You are the scheduler."


def test_apply_creates_processes_with_bindings(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "scheduler"

    handlers = repo.list_handlers(process_id=procs[0].id)
    assert len(handlers) == 1
    assert handlers[0].event_pattern == "scheduler:tick"


def test_apply_upsert_is_idempotent(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)
    apply_image(spec, repo)

    assert len(repo.list_capabilities()) == 1
    assert len(repo.list_processes()) == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_image_apply.py -v`
Expected: FAIL (module not found)

**Step 3: Implement apply_image**

```python
# src/cogos/image/apply.py
"""Apply an ImageSpec to a CogOS repository."""

from __future__ import annotations

import logging

from cogos.db.models import (
    Capability,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
)
from cogos.files.store import FileStore
from cogos.image.spec import ImageSpec

logger = logging.getLogger(__name__)


def apply_image(spec: ImageSpec, repo, *, clean: bool = False) -> dict[str, int]:
    """Apply an image spec to the database. Returns counts of entities created/updated."""
    counts = {"capabilities": 0, "resources": 0, "files": 0, "processes": 0, "cron": 0}

    # 1. Capabilities
    for cap_dict in spec.capabilities:
        cap = Capability(
            name=cap_dict["name"],
            handler=cap_dict["handler"],
            description=cap_dict.get("description", ""),
            instructions=cap_dict.get("instructions", ""),
            input_schema=cap_dict.get("input_schema") or {},
            output_schema=cap_dict.get("output_schema") or {},
            iam_role_arn=cap_dict.get("iam_role_arn"),
            metadata=cap_dict.get("metadata") or {},
        )
        repo.upsert_capability(cap)
        counts["capabilities"] += 1

    # 2. Files
    fs = FileStore(repo)
    for key, content in spec.files.items():
        fs.upsert(key, content, source="image")
        counts["files"] += 1

    # 3. Processes (with capability bindings and handlers)
    for proc_dict in spec.processes:
        code_id = None
        if proc_dict.get("code_key"):
            f = repo.get_file_by_key(proc_dict["code_key"])
            if f:
                code_id = f.id

        mode = ProcessMode(proc_dict.get("mode", "one_shot"))
        p = Process(
            name=proc_dict["name"],
            mode=mode,
            content=proc_dict.get("content", ""),
            code=code_id,
            runner=proc_dict.get("runner", "lambda"),
            model=proc_dict.get("model"),
            priority=float(proc_dict.get("priority", 0.0)),
            status=ProcessStatus.WAITING if mode == ProcessMode.DAEMON else ProcessStatus.RUNNABLE,
            metadata=proc_dict.get("metadata") or {},
        )
        pid = repo.upsert_process(p)

        # Bind capabilities
        for cap_name in proc_dict.get("capabilities", []):
            cap = repo.get_capability_by_name(cap_name)
            if cap:
                pc = ProcessCapability(process=pid, capability=cap.id)
                repo.create_process_capability(pc)

        # Create handlers
        for pattern in proc_dict.get("handlers", []):
            h = Handler(process=pid, event_pattern=pattern, enabled=True)
            repo.create_handler(h)

        counts["processes"] += 1

    return counts
```

**Step 4: Run tests**

Run: `python -m pytest tests/cogos/test_image_apply.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/apply.py tests/cogos/test_image_apply.py
git commit -m "feat(cogos): add apply_image to upsert ImageSpec into repository"
```

---

### Task 3: snapshot_image

**Files:**
- Create: `src/cogos/image/snapshot.py`
- Create: `tests/cogos/test_image_snapshot.py`

**Step 1: Write the test**

```python
# tests/cogos/test_image_snapshot.py
import tempfile
from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.image.spec import ImageSpec, load_image
from cogos.image.apply import apply_image
from cogos.image.snapshot import snapshot_image


def test_snapshot_round_trips(tmp_path):
    """Apply an image, snapshot it, load the snapshot — should match."""
    repo = LocalRepository(str(tmp_path / "db"))

    original = ImageSpec(
        capabilities=[
            {"name": "files", "handler": "cogos.capabilities.files.FilesCapability",
             "description": "File store", "instructions": "", "input_schema": None,
             "output_schema": None, "iam_role_arn": None, "metadata": None},
        ],
        resources=[],
        processes=[
            {"name": "scheduler", "mode": "daemon", "content": "scheduler daemon",
             "code_key": "cogos/scheduler", "runner": "lambda", "model": None,
             "priority": 100.0, "capabilities": ["files"],
             "handlers": ["scheduler:tick"], "metadata": {}},
        ],
        cron_rules=[],
        files={"cogos/scheduler": "You are the scheduler."},
    )
    apply_image(original, repo)

    snapshot_dir = tmp_path / "snapshot"
    snapshot_image(repo, snapshot_dir)

    # Verify files were generated
    assert (snapshot_dir / "init" / "capabilities.py").exists()
    assert (snapshot_dir / "init" / "processes.py").exists()
    assert (snapshot_dir / "files" / "cogos" / "scheduler").exists()
    assert (snapshot_dir / "README.md").exists()

    # Round-trip: load the snapshot and verify
    restored = load_image(snapshot_dir)
    assert len(restored.capabilities) == 1
    assert restored.capabilities[0]["name"] == "files"
    assert len(restored.processes) == 1
    assert restored.processes[0]["name"] == "scheduler"
    assert "files" in restored.processes[0]["capabilities"]
    assert "scheduler:tick" in restored.processes[0]["handlers"]
    assert restored.files["cogos/scheduler"] == "You are the scheduler."
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_image_snapshot.py -v`
Expected: FAIL (module not found)

**Step 3: Implement snapshot_image**

```python
# src/cogos/image/snapshot.py
"""Snapshot a running cogent's state into an image directory."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _repr_val(v) -> str:
    """Format a Python value for source code output."""
    if v is None:
        return "None"
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return repr(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = ", ".join(f"{_repr_val(k)}: {_repr_val(val)}" for k, val in v.items())
        return "{" + items + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        items = ", ".join(_repr_val(i) for i in v)
        return "[" + items + "]"
    return repr(v)


def snapshot_image(repo, output_dir: Path, *, cogent_name: str | None = None) -> None:
    """Read DB state and generate an image directory."""
    init_dir = output_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)
    files_dir = output_dir / "files"

    # -- Capabilities --
    caps = repo.list_capabilities()
    lines = []
    for c in caps:
        parts = [f'add_capability({_repr_val(c.name)}']
        parts.append(f'    handler={_repr_val(c.handler)}')
        if c.description:
            parts.append(f'    description={_repr_val(c.description)}')
        if c.instructions:
            parts.append(f'    instructions={_repr_val(c.instructions)}')
        if c.input_schema:
            parts.append(f'    input_schema={_repr_val(c.input_schema)}')
        if c.output_schema:
            parts.append(f'    output_schema={_repr_val(c.output_schema)}')
        if c.iam_role_arn:
            parts.append(f'    iam_role_arn={_repr_val(c.iam_role_arn)}')
        if c.metadata:
            parts.append(f'    metadata={_repr_val(c.metadata)}')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "capabilities.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Resources --
    # Resources not yet in LocalRepository — write empty for now
    (init_dir / "resources.py").write_text("")

    # -- Processes --
    procs = repo.list_processes()
    lines = []
    for p in procs:
        # Get capability names
        cap_names = []
        try:
            pcs = repo.list_process_capabilities(p.id)
            for pc in pcs:
                cap = repo.get_capability(pc.capability)
                if cap:
                    cap_names.append(cap.name)
        except (AttributeError, TypeError):
            pass

        # Get handler patterns
        handler_patterns = []
        try:
            handlers = repo.list_handlers(process_id=p.id)
            handler_patterns = [h.event_pattern for h in handlers]
        except (AttributeError, TypeError):
            pass

        # Get code_key
        code_key = None
        if p.code:
            try:
                f = repo.get_file_by_id(p.code)
                if f:
                    code_key = f.key
            except (AttributeError, TypeError):
                pass

        parts = [f'add_process({_repr_val(p.name)}']
        parts.append(f'    mode={_repr_val(p.mode.value)}')
        if p.content:
            parts.append(f'    content={_repr_val(p.content)}')
        if code_key:
            parts.append(f'    code_key={_repr_val(code_key)}')
        parts.append(f'    runner={_repr_val(p.runner)}')
        if p.model:
            parts.append(f'    model={_repr_val(p.model)}')
        parts.append(f'    priority={_repr_val(p.priority)}')
        if cap_names:
            parts.append(f'    capabilities={_repr_val(cap_names)}')
        if handler_patterns:
            parts.append(f'    handlers={_repr_val(handler_patterns)}')
        if p.metadata:
            parts.append(f'    metadata={_repr_val(p.metadata)}')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "processes.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Cron --
    (init_dir / "cron.py").write_text("")

    # -- Files --
    file_list = repo.list_files()
    for f in file_list:
        fv = repo.get_active_file_version(f.id)
        if fv and fv.content:
            out_path = files_dir / f.key
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(fv.content)

    # -- README --
    now = datetime.utcnow().isoformat(timespec="seconds")
    source = f" from cogent `{cogent_name}`" if cogent_name else ""
    readme = (
        f"# Snapshot{source}\n\n"
        f"Generated: {now}Z\n\n"
        f"- {len(caps)} capabilities\n"
        f"- {len(procs)} processes\n"
        f"- {len(file_list)} files\n"
    )
    (output_dir / "README.md").write_text(readme)
```

**Step 4: Run tests**

Run: `python -m pytest tests/cogos/test_image_snapshot.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/snapshot.py tests/cogos/test_image_snapshot.py
git commit -m "feat(cogos): add snapshot_image to capture running state as image"
```

---

### Task 4: CLI — image subgroup (boot, snapshot, list)

**Files:**
- Modify: `src/cogos/cli/__main__.py`

**Step 1: Add `image` subgroup with `boot`, `snapshot`, `list` commands**

Add after the existing `cogos` group definition (around line 118), replacing the `bootstrap` command (lines 124-356):

Remove the entire `bootstrap` function (lines 124-356).

Add the `image` subgroup:

```python
# ═══════════════════════════════════════════════════════════
# IMAGE commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def image():
    """Manage CogOS images (boot, snapshot, list)."""


@image.command()
@click.argument("name")
@click.option("--clean", is_flag=True, help="Wipe all tables before loading")
@click.pass_context
def boot(ctx: click.Context, name: str, clean: bool):
    """Boot CogOS from an image."""
    from cogos.image.spec import load_image
    from cogos.image.apply import apply_image

    # Find image directory
    repo_root = Path(__file__).resolve().parents[3]
    image_dir = repo_root / "images" / name
    if not image_dir.is_dir():
        click.echo(f"Image not found: {image_dir}")
        return

    repo = _repo()

    # Run migration
    migration = Path(__file__).parent.parent / "db" / "migrations" / "001_create_tables.sql"
    if migration.exists():
        sql = migration.read_text()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    repo.execute(stmt)
                except Exception as e:
                    if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                        pass
                    else:
                        click.echo(f"  Warning: {e}")
        click.echo("Migration applied.")

    if clean:
        for table in ["cogos_trace", "cogos_run", "cogos_event_delivery",
                       "cogos_event", "cogos_handler", "cogos_process_capability",
                       "cogos_file_version", "cogos_file", "cogos_process", "cogos_capability"]:
            try:
                repo.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        click.echo("Tables cleaned.")

    spec = load_image(image_dir)
    counts = apply_image(spec, repo)

    click.echo(
        f"Boot complete: {counts['capabilities']} capabilities, "
        f"{counts['files']} files, {counts['processes']} processes"
    )


@image.command()
@click.argument("name")
@click.pass_context
def snapshot(ctx: click.Context, name: str):
    """Snapshot running CogOS state into an image."""
    from cogos.image.snapshot import snapshot_image

    repo_root = Path(__file__).resolve().parents[3]
    output_dir = repo_root / "images" / name
    if output_dir.exists():
        click.echo(f"Image already exists: {output_dir}")
        click.echo("Remove it first or choose a different name.")
        return

    repo = _repo()
    cogent_name = ctx.obj.get("cogent_name")
    snapshot_image(repo, output_dir, cogent_name=cogent_name)
    click.echo(f"Snapshot saved to images/{name}/")


@image.command("list")
def image_list():
    """List available images."""
    from cogos.image.spec import load_image

    repo_root = Path(__file__).resolve().parents[3]
    images_dir = repo_root / "images"
    if not images_dir.is_dir():
        click.echo("No images/ directory found.")
        return

    for d in sorted(images_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            spec = load_image(d)
            click.echo(
                f"  {d.name:20s}  {len(spec.capabilities)} caps, "
                f"{len(spec.resources)} resources, {len(spec.processes)} procs, "
                f"{len(spec.cron_rules)} cron, {len(spec.files)} files"
            )
        except Exception as e:
            click.echo(f"  {d.name:20s}  (error: {e})")
```

**Step 2: Run the CLI to verify**

Run: `python -m cogos.cli --help`
Expected: Shows `image` subgroup, no `bootstrap` command

Run: `python -m cogos.cli image --help`
Expected: Shows `boot`, `snapshot`, `list` subcommands

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "feat(cogos): add image CLI subgroup (boot, snapshot, list), remove bootstrap"
```

---

### Task 5: Migrate cogent-v1 image to add_*() format

**Files:**
- Modify: `images/cogent-v1/init/resources.py` → rewrite with `add_resource()` calls
- Create: `images/cogent-v1/init/capabilities.py` → extracted from resources.py, uses `add_capability()` calls
- Modify: `images/cogent-v1/init/cron.py` → rewrite with `add_cron()` calls
- Rename: `images/cogent-v1/init/run.py` → `images/cogent-v1/init/processes.py`, rewrite with `add_process()` calls
- Delete: `images/cogent-v1/init/__init__.py`

**Step 1: Write the new files**

`images/cogent-v1/init/capabilities.py`:
```python
from cogos.capabilities import BUILTIN_CAPABILITIES

for cap in BUILTIN_CAPABILITIES:
    add_capability(
        cap["name"],
        handler=cap["handler"],
        description=cap.get("description", ""),
    )
```

`images/cogent-v1/init/resources.py`:
```python
add_resource("lambda_slots", type="pool", capacity=5, metadata={"description": "Concurrent Lambda executor slots"})
add_resource("ecs_slots", type="pool", capacity=2, metadata={"description": "Concurrent ECS task slots"})
```

`images/cogent-v1/init/processes.py`:
```python
add_process(
    "scheduler",
    mode="daemon",
    content="CogOS scheduler daemon",
    code_key="cogos/scheduler",
    runner="lambda",
    priority=100.0,
    capabilities=[
        "scheduler/match_events",
        "scheduler/select_processes",
        "scheduler/dispatch_process",
        "scheduler/unblock_processes",
        "scheduler/kill_process",
    ],
    handlers=["scheduler:tick"],
)
```

`images/cogent-v1/init/cron.py`:
```python
add_cron("* * * * *", event_type="scheduler:tick")
```

**Step 2: Test that the image loads correctly**

Run: `python -c "from cogos.image.spec import load_image; from pathlib import Path; s = load_image(Path('images/cogent-v1')); print(f'{len(s.capabilities)} caps, {len(s.resources)} res, {len(s.processes)} procs, {len(s.cron_rules)} cron, {len(s.files)} files')"`

Expected: `7 caps, 2 res, 1 procs, 1 cron, 1 files`

**Step 3: Delete old files**

```bash
rm images/cogent-v1/init/__init__.py
rm images/cogent-v1/init/run.py
```

**Step 4: Update README.md**

Update `images/cogent-v1/README.md` to reflect new structure (remove references to `__init__.py` and old module exports).

**Step 5: Commit**

```bash
git add images/cogent-v1/
git commit -m "refactor(images): migrate cogent-v1 to add_*() builder format"
```

---

### Task 6: End-to-end test — boot from cogent-v1

**Files:**
- Create: `tests/cogos/test_image_e2e.py`

**Step 1: Write end-to-end test**

```python
# tests/cogos/test_image_e2e.py
from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.image.spec import load_image
from cogos.image.apply import apply_image
from cogos.image.snapshot import snapshot_image


def test_boot_cogent_v1(tmp_path):
    """Boot from the real cogent-v1 image using LocalRepository."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"
    assert image_dir.is_dir(), f"cogent-v1 image not found at {image_dir}"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)

    assert len(spec.capabilities) >= 7
    assert len(spec.resources) == 2
    assert len(spec.processes) == 1
    assert len(spec.cron_rules) == 1
    assert len(spec.files) >= 1

    counts = apply_image(spec, repo)
    assert counts["capabilities"] >= 7
    assert counts["processes"] == 1
    assert counts["files"] >= 1

    # Verify scheduler process exists with bindings
    procs = repo.list_processes()
    scheduler = [p for p in procs if p.name == "scheduler"]
    assert len(scheduler) == 1

    handlers = repo.list_handlers(process_id=scheduler[0].id)
    assert any(h.event_pattern == "scheduler:tick" for h in handlers)


def test_boot_then_snapshot_round_trip(tmp_path):
    """Boot cogent-v1, snapshot, boot snapshot — should produce same state."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"

    # Boot original
    repo1 = LocalRepository(str(tmp_path / "db1"))
    spec1 = load_image(image_dir)
    apply_image(spec1, repo1)

    # Snapshot
    snap_dir = tmp_path / "snapshot"
    snapshot_image(repo1, snap_dir, cogent_name="test")

    # Boot from snapshot
    repo2 = LocalRepository(str(tmp_path / "db2"))
    spec2 = load_image(snap_dir)
    apply_image(spec2, repo2)

    # Compare
    assert len(repo1.list_capabilities()) == len(repo2.list_capabilities())
    assert len(repo1.list_processes()) == len(repo2.list_processes())

    for c1 in repo1.list_capabilities():
        c2 = repo2.get_capability_by_name(c1.name)
        assert c2 is not None, f"Missing capability: {c1.name}"
        assert c2.handler == c1.handler
```

**Step 2: Run tests**

Run: `python -m pytest tests/cogos/test_image_e2e.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/cogos/test_image_e2e.py
git commit -m "test(cogos): add end-to-end image boot and round-trip tests"
```
