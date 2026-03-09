"""cogent cogos — unified CLI for all CogOS subsystems.

Usage:
    cogent <name> cogos capability list
    cogent <name> cogos process create my-proc --mode daemon
    cogent <name> cogos handler add my-proc "github.issue.opened"
    cogent <name> cogos file get prompts/scheduler
    cogent <name> cogos event emit deploy.started --payload '{"env":"staging"}'
    cogent <name> cogos run list --process scheduler
    cogent <name> cogos resource list
    cogent <name> cogos secret get /myapp/api-key
    cogent <name> cogos sync ./definitions
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import click


def _repo():
    from cogos.db.repository import Repository
    return Repository.create()


def _output(data, *, use_json: bool = False) -> None:
    if use_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    if isinstance(data, list):
        for item in data:
            _output_single(item)
            click.echo()
    else:
        _output_single(data)


def _output_single(data: dict) -> None:
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            click.echo(f"  {key}: {json.dumps(value, default=str)}")
        else:
            click.echo(f"  {key}: {value}")


# ═══════════════════════════════════════════════════════════
# ROOT GROUP
# ═══════════════════════════════════════════════════════════

@click.group("cogos")
def cogos():
    """CogOS — manage processes, capabilities, files, events, and more."""


# ═══════════════════════════════════════════════════════════
# CAPABILITY
# ═══════════════════════════════════════════════════════════

@cogos.group()
def capability():
    """Manage capabilities (what processes can do)."""


@capability.command("list")
@click.option("--json", "use_json", is_flag=True)
def capability_list(use_json: bool):
    """List all capabilities."""
    repo = _repo()
    caps = repo.list_capabilities()
    data = [
        {"name": c.name, "handler": c.handler, "enabled": c.enabled, "id": str(c.id)}
        for c in caps
    ]
    _output(data, use_json=use_json)


@capability.command("get")
@click.argument("name")
@click.option("--json", "use_json", is_flag=True)
def capability_get(name: str, use_json: bool):
    """Show a capability by name."""
    repo = _repo()
    cap = repo.get_capability_by_name(name)
    if not cap:
        click.echo(f"Not found: {name}", err=True)
        raise SystemExit(1)
    _output(cap.model_dump(mode="json"), use_json=use_json)


@capability.command("enable")
@click.argument("name")
def capability_enable(name: str):
    """Enable a capability."""
    repo = _repo()
    cap = repo.get_capability_by_name(name)
    if not cap:
        click.echo(f"Not found: {name}", err=True)
        raise SystemExit(1)
    repo.execute(
        "UPDATE cogos_capability SET enabled = TRUE, updated_at = now() WHERE id = :id",
        {"id": cap.id},
    )
    click.echo(f"Enabled: {name}")


@capability.command("disable")
@click.argument("name")
def capability_disable(name: str):
    """Disable a capability."""
    repo = _repo()
    cap = repo.get_capability_by_name(name)
    if not cap:
        click.echo(f"Not found: {name}", err=True)
        raise SystemExit(1)
    repo.execute(
        "UPDATE cogos_capability SET enabled = FALSE, updated_at = now() WHERE id = :id",
        {"id": cap.id},
    )
    click.echo(f"Disabled: {name}")


@capability.command("load")
@click.argument("directory", type=click.Path(exists=True))
def capability_load(directory: str):
    """Load Capability definitions from .py files containing Capability instances."""
    from cogents.loader.capability import sync_capabilities
    repo = _repo()
    synced, errors = sync_capabilities(Path(directory), repo)
    click.echo(f"Capabilities: {synced} synced, {errors} errors")


# ═══════════════════════════════════════════════════════════
# PROCESS
# ═══════════════════════════════════════════════════════════

@cogos.group()
def process():
    """Manage processes (the active entities in CogOS)."""


@process.command("list")
@click.option("--status", "filter_status", default=None,
              type=click.Choice(["waiting", "runnable", "running", "blocked",
                                 "suspended", "completed", "disabled"]))
@click.option("--json", "use_json", is_flag=True)
def process_list(filter_status: str | None, use_json: bool):
    """List processes."""
    repo = _repo()
    procs = repo.list_processes()
    if filter_status:
        procs = [p for p in procs if p.status.value == filter_status]
    data = [
        {"name": p.name, "mode": p.mode.value, "status": p.status.value,
         "priority": p.priority, "runner": p.runner, "id": str(p.id)}
        for p in procs
    ]
    _output(data, use_json=use_json)


@process.command("get")
@click.argument("name")
@click.option("--json", "use_json", is_flag=True)
def process_get(name: str, use_json: bool):
    """Show a process by name."""
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Not found: {name}", err=True)
        raise SystemExit(1)
    _output(p.model_dump(mode="json"), use_json=use_json)


@process.command("create")
@click.argument("name")
@click.option("--mode", type=click.Choice(["daemon", "one_shot"]), default="one_shot")
@click.option("--content", default="")
@click.option("--code-key", default=None, help="File key for prompt template")
@click.option("--runner", type=click.Choice(["lambda", "ecs"]), default="lambda")
@click.option("--model", default=None)
@click.option("--priority", type=float, default=0.0)
def process_create(name: str, mode: str, content: str, code_key: str | None,
                   runner: str, model: str | None, priority: float):
    """Create a new process."""
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = _repo()
    code_id = None
    if code_key:
        f = repo.get_file_by_key(code_key)
        if f:
            code_id = f.id
        else:
            click.echo(f"Warning: file '{code_key}' not found")
    p = Process(
        name=name, mode=ProcessMode(mode), content=content,
        code=code_id, runner=runner, model=model, priority=priority,
        status=ProcessStatus.RUNNABLE,
    )
    pid = repo.upsert_process(p)
    click.echo(f"Created: {name} ({pid})")


@process.command("disable")
@click.argument("name")
def process_disable(name: str):
    """Disable a process."""
    from cogos.db.models import ProcessStatus
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Not found: {name}", err=True)
        raise SystemExit(1)
    repo.update_process_status(p.id, ProcessStatus.DISABLED)
    click.echo(f"Disabled: {name}")


@process.command("enable")
@click.argument("name")
def process_enable(name: str):
    """Set a process to RUNNABLE."""
    from cogos.db.models import ProcessStatus
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Not found: {name}", err=True)
        raise SystemExit(1)
    repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
    click.echo(f"Enabled: {name}")


@process.command("load")
@click.argument("directory", type=click.Path(exists=True))
def process_load(directory: str):
    """Load Process definitions from .py files containing Process instances.

    Also syncs inline handlers and capability bindings declared in
    metadata["handlers"] and metadata["capabilities"].
    """
    from cogents.loader.process import sync_processes
    repo = _repo()
    synced, errors = sync_processes(Path(directory), repo)
    click.echo(f"Processes: {synced} synced, {errors} errors")


# ═══════════════════════════════════════════════════════════
# HANDLER
# ═══════════════════════════════════════════════════════════

@cogos.group()
def handler():
    """Manage handlers (bind processes to event patterns)."""


@handler.command("list")
@click.option("--process", "process_name", default=None, help="Filter by process name")
@click.option("--json", "use_json", is_flag=True)
def handler_list(process_name: str | None, use_json: bool):
    """List handlers."""
    repo = _repo()
    pid = None
    if process_name:
        p = repo.get_process_by_name(process_name)
        if not p:
            click.echo(f"Process not found: {process_name}", err=True)
            raise SystemExit(1)
        pid = p.id
    handlers = repo.list_handlers(process_id=pid)
    proc_cache: dict[str, str] = {}
    data = []
    for h in handlers:
        pkey = str(h.process)
        if pkey not in proc_cache:
            proc = repo.get_process(h.process)
            proc_cache[pkey] = proc.name if proc else pkey
        data.append({
            "process": proc_cache[pkey], "event_pattern": h.event_pattern,
            "enabled": h.enabled, "id": str(h.id),
        })
    _output(data, use_json=use_json)


@handler.command("add")
@click.argument("process_name")
@click.argument("event_pattern")
def handler_add(process_name: str, event_pattern: str):
    """Bind a process to an event pattern."""
    from cogos.db.models import Handler as HandlerModel
    repo = _repo()
    p = repo.get_process_by_name(process_name)
    if not p:
        click.echo(f"Process not found: {process_name}", err=True)
        raise SystemExit(1)
    h = HandlerModel(process=p.id, event_pattern=event_pattern, enabled=True)
    hid = repo.create_handler(h)
    click.echo(f"Handler: {event_pattern} -> {process_name} ({hid})")


@handler.command("remove")
@click.argument("handler_id")
def handler_remove(handler_id: str):
    """Remove a handler by ID."""
    repo = _repo()
    ok = repo.delete_handler(UUID(handler_id))
    click.echo(f"Removed: {handler_id}" if ok else f"Not found: {handler_id}")


# ═══════════════════════════════════════════════════════════
# FILE
# ═══════════════════════════════════════════════════════════

@cogos.group()
def file():
    """Manage files (versioned hierarchical store)."""


@file.command("list")
@click.option("--prefix", default=None)
@click.option("--json", "use_json", is_flag=True)
def file_list(prefix: str | None, use_json: bool):
    """List files."""
    repo = _repo()
    files = repo.list_files(prefix=prefix)
    data = [{"key": f.key, "id": str(f.id)} for f in files]
    _output(data, use_json=use_json)


@file.command("get")
@click.argument("key")
def file_get(key: str):
    """Show file content by key."""
    from cogos.files.store import FileStore
    repo = _repo()
    content = FileStore(repo).get_content(key)
    if content is None:
        click.echo(f"Not found: {key}", err=True)
        raise SystemExit(1)
    click.echo(content)


@file.command("put")
@click.argument("key")
@click.argument("content")
@click.option("--source", default="cli")
def file_put(key: str, content: str, source: str):
    """Create or update a file."""
    from cogos.files.store import FileStore
    repo = _repo()
    result = FileStore(repo).upsert(key, content, source=source)
    if result is None:
        click.echo(f"Unchanged: {key}")
    else:
        click.echo(f"Written: {key}")


@file.command("load")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--source", default="cli")
def file_load(directory: str, source: str):
    """Load .md and .py files from a directory into the file store."""
    from cogos.files.store import FileStore
    repo = _repo()
    fs = FileStore(repo)
    dir_path = Path(directory).resolve()
    created = updated = unchanged = 0
    for fp in sorted(dir_path.rglob("*")):
        if not fp.is_file() or fp.suffix not in (".md", ".py") or fp.name.startswith("."):
            continue
        key = str(fp.relative_to(dir_path))
        result = fs.upsert(key, fp.read_text(encoding="utf-8"), source=source)
        if result is None:
            unchanged += 1
        elif hasattr(result, "key"):
            created += 1
            click.echo(f"  Created: {key}")
        else:
            updated += 1
            click.echo(f"  Updated: {key}")
    click.echo(f"Files: {created} created, {updated} updated, {unchanged} unchanged")


# ═══════════════════════════════════════════════════════════
# EVENT
# ═══════════════════════════════════════════════════════════

@cogos.group()
def event():
    """Manage events (append-only log)."""


@event.command("list")
@click.option("--type", "event_type", default=None)
@click.option("--limit", type=int, default=20)
@click.option("--json", "use_json", is_flag=True)
def event_list(event_type: str | None, limit: int, use_json: bool):
    """List events."""
    repo = _repo()
    events = repo.get_events(event_type=event_type, limit=limit)
    data = [
        {"id": str(e.id), "type": e.event_type, "source": e.source,
         "created_at": str(e.created_at)}
        for e in events
    ]
    _output(data, use_json=use_json)


@event.command("emit")
@click.argument("event_type")
@click.option("--payload", default="{}")
def event_emit(event_type: str, payload: str):
    """Emit an event."""
    from cogos.db.models import Event
    repo = _repo()
    evt = Event(event_type=event_type, source="cli", payload=json.loads(payload))
    eid = repo.append_event(evt)
    click.echo(f"Emitted: {event_type} ({eid})")


# ═══════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════

@cogos.group()
def run():
    """View execution history."""


@run.command("list")
@click.option("--process", "process_name", default=None)
@click.option("--limit", type=int, default=20)
@click.option("--json", "use_json", is_flag=True)
def run_list(process_name: str | None, limit: int, use_json: bool):
    """List runs."""
    repo = _repo()
    pid = None
    if process_name:
        p = repo.get_process_by_name(process_name)
        if p:
            pid = p.id
    runs = repo.list_runs(process_id=pid, limit=limit)
    data = [
        {"id": str(r.id), "process": str(r.process), "status": r.status.value,
         "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
         "duration_ms": r.duration_ms, "created_at": str(r.created_at)}
        for r in runs
    ]
    _output(data, use_json=use_json)


@run.command("show")
@click.argument("run_id")
@click.option("--json", "use_json", is_flag=True)
def run_show(run_id: str, use_json: bool):
    """Show run details."""
    repo = _repo()
    r = repo.get_run(UUID(run_id))
    if not r:
        click.echo(f"Not found: {run_id}", err=True)
        raise SystemExit(1)
    _output(r.model_dump(mode="json"), use_json=use_json)


# ═══════════════════════════════════════════════════════════
# SECRET
# ═══════════════════════════════════════════════════════════

@cogos.group()
def secret():
    """Manage secrets (key manager integration)."""


@secret.command("get")
@click.argument("key")
@click.option("--manager", type=click.Choice(["ssm", "secretsmanager"]), default="ssm")
def secret_get(key: str, manager: str):
    """Retrieve a secret from the key manager."""
    from cogos.capabilities.secrets import SecretsCapability, SecretError
    from uuid import uuid4
    cap = SecretsCapability(repo=None, process_id=uuid4())
    result = cap.get(key=key)
    if isinstance(result, SecretError):
        click.echo(f"Error: {result.error}", err=True)
        raise SystemExit(1)
    if isinstance(result.value, (dict, list)):
        click.echo(json.dumps(result.value, indent=2))
    else:
        click.echo(result.value)


# ═══════════════════════════════════════════════════════════
# SYNC (bulk load capabilities + processes)
# ═══════════════════════════════════════════════════════════

@cogos.command()
@click.argument("directory", type=click.Path(exists=True))
def sync(directory: str):
    """Sync capability and process definitions from a directory.

    Scans DIR/capabilities/ for Capability instances and DIR/processes/
    for Process instances, upserting them into the datastore.
    If the subdirectories don't exist, scans DIR directly for both types.
    """
    from cogents.loader.capability import sync_capabilities
    from cogents.loader.process import sync_processes

    repo = _repo()
    root = Path(directory).resolve()

    cap_dir = root / "capabilities"
    proc_dir = root / "processes"

    if cap_dir.is_dir():
        cs, ce = sync_capabilities(cap_dir, repo)
    else:
        cs, ce = sync_capabilities(root, repo)

    if proc_dir.is_dir():
        ps, pe = sync_processes(proc_dir, repo)
    else:
        ps, pe = sync_processes(root, repo)

    click.echo(f"Capabilities: {cs} synced, {ce} errors")
    click.echo(f"Processes: {ps} synced, {pe} errors")


# ═══════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════

@cogos.command()
def status():
    """Show CogOS subsystem summary."""
    repo = _repo()

    procs = repo.list_processes()
    by_status: dict[str, int] = {}
    for p in procs:
        by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
    status_str = ", ".join(f"{v} {k}" for k, v in sorted(by_status.items()))
    click.echo(f"Processes: {len(procs)} ({status_str})")

    caps = repo.list_capabilities()
    enabled = sum(1 for c in caps if c.enabled)
    click.echo(f"Capabilities: {len(caps)} ({enabled} enabled)")

    files = repo.list_files()
    click.echo(f"Files: {len(files)}")

    handlers = repo.list_handlers()
    click.echo(f"Handlers: {len(handlers)}")

    events = repo.get_events(limit=5)
    click.echo(f"Recent events:")
    for e in events:
        click.echo(f"  {e.event_type} ({e.created_at})")
