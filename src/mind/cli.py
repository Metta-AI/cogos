"""Mind CLI — CRUD interface for programs, tasks, triggers, and cron.

All commands write to the brain's database via the Repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

import click

from brain.db.models import (
    Cron,
    Event,
    Program,
    ProgramType,
    Resource,
    ResourceType,
    RunStatus,
    Task,
    TaskStatus,
    Trigger,
    TriggerConfig,
)
from brain.db.repository import Repository
from mind.program import load_program, load_programs_dir, sync_program, validate_tools


def _repo() -> Repository:
    """Create a repository from environment variables."""
    return Repository.create()


def _output(data: dict | list, *, use_json: bool = False) -> None:
    """Print output in plain text or JSON."""
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
    """Print a single record as plain text."""
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            click.echo(f"  {key}: {json.dumps(value, default=str)}")
        else:
            click.echo(f"  {key}: {value}")


# ═══════════════════════════════════════════════════════════
# ROOT
# ═══════════════════════════════════════════════════════════


@click.group()
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.pass_context
def mind(ctx: click.Context, use_json: bool) -> None:
    """Manage programs, tasks, triggers, and cron schedules."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = use_json


# ═══════════════════════════════════════════════════════════
# PROGRAMS
# ═══════════════════════════════════════════════════════════


_DEFAULT_PROGRAMS_DIR = "eggs/ovo/programs"


@mind.group()
def program() -> None:
    """Manage programs."""


@program.command("list")
@click.option("--max", "limit", type=int, default=50, help="Max programs to show")
@click.option("--all", "show_all", is_flag=True, help="Include disabled programs")
@click.option("--disabled", is_flag=True, help="Show only disabled programs")
@click.pass_context
def program_list(ctx: click.Context, limit: int, show_all: bool, disabled: bool) -> None:
    """List all programs."""
    repo = _repo()
    programs = repo.list_programs()

    if disabled:
        programs = [p for p in programs if not p.metadata.get("enabled", True)]
    elif not show_all:
        programs = [p for p in programs if p.metadata.get("enabled", True)]

    programs = programs[:limit]
    data = [
        {
            "name": p.name,
            "type": p.program_type.value,
            "enabled": p.metadata.get("enabled", True),
            "includes": p.includes,
            "tools": p.tools,
        }
        for p in programs
    ]
    _output(data, use_json=ctx.obj["json"])


@program.command("info")
@click.argument("name")
@click.pass_context
def program_info(ctx: click.Context, name: str) -> None:
    """Show a program's details."""
    repo = _repo()
    prog = repo.get_program(name)
    if not prog:
        click.echo(f"Program '{name}' not found.", err=True)
        sys.exit(1)
    _output(prog.model_dump(mode="json"), use_json=ctx.obj["json"])


@program.command("add")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def program_add(ctx: click.Context, path: str) -> None:
    """Add a program from a .py or .md file.

    Validates tools, checks memory includes, and registers triggers.
    """
    bundle = load_program(Path(path))
    repo = _repo()
    prog_id, issues = sync_program(bundle, repo)

    for issue in issues:
        prefix = "ERROR" if issue.level == "error" else "WARN"
        click.echo(f"  [{prefix}] {issue.program}: {issue.message}", err=True)

    if not prog_id:
        click.echo("Failed to add program (see errors above).", err=True)
        sys.exit(1)

    result = {"id": prog_id, "name": bundle.program.name, "status": "added"}
    if bundle.triggers:
        result["triggers"] = len(bundle.triggers)
    _output(result, use_json=ctx.obj["json"])


@program.command("delete")
@click.argument("name")
@click.pass_context
def program_delete(ctx: click.Context, name: str) -> None:
    """Delete a program."""
    repo = _repo()
    if repo.delete_program(name):
        _output({"name": name, "status": "deleted"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Program '{name}' not found.", err=True)
        sys.exit(1)


@program.command("disable")
@click.argument("name")
@click.option("--enable", is_flag=True, help="Re-enable instead of disabling")
@click.pass_context
def program_disable(ctx: click.Context, name: str, enable: bool) -> None:
    """Disable (or --enable) a program."""
    repo = _repo()
    prog = repo.get_program(name)
    if not prog:
        click.echo(f"Program '{name}' not found.", err=True)
        sys.exit(1)
    prog.metadata["enabled"] = enable
    repo.upsert_program(prog)
    state = "enabled" if enable else "disabled"
    _output({"name": name, "status": state}, use_json=ctx.obj["json"])


@program.command("runs")
@click.argument("name")
@click.option("--limit", type=int, default=20)
@click.pass_context
def program_runs(ctx: click.Context, name: str, limit: int) -> None:
    """List recent runs for a program."""
    repo = _repo()
    runs = repo.query_runs(program_name=name, limit=limit)
    data = [
        {
            "id": str(r.id),
            "status": r.status.value,
            "tokens": r.tokens_input + r.tokens_output,
            "cost_usd": str(r.cost_usd),
            "duration_ms": r.duration_ms,
            "started_at": str(r.started_at) if r.started_at else None,
        }
        for r in runs
    ]
    _output(data, use_json=ctx.obj["json"])


@program.command("update")
@click.argument("path", default=_DEFAULT_PROGRAMS_DIR, type=click.Path())
@click.option("--dry-run", is_flag=True, help="Show what would change without writing")
@click.pass_context
def program_update(ctx: click.Context, path: str, dry_run: bool) -> None:
    """Sync programs from a directory (recursive .py/.md files).

    Validates tools, checks memory includes, and registers triggers.
    Default path: eggs/ovo/programs/
    """
    root = Path(path)
    if not root.is_dir():
        click.echo(f"Not a directory: {root}", err=True)
        sys.exit(1)

    bundles = load_programs_dir(root)
    if not bundles:
        click.echo(f"No .py or .md program files found under {root}", err=True)
        sys.exit(1)

    if dry_run:
        all_issues: list = []
        for b in bundles:
            tool_issues = validate_tools(b)
            all_issues.extend(tool_issues)
            trigs = f" +{len(b.triggers)} triggers" if b.triggers else ""
            click.echo(f"  {b.program.name} ({b.program.program_type.value}){trigs}")
        for issue in all_issues:
            prefix = "ERROR" if issue.level == "error" else "WARN"
            click.echo(f"  [{prefix}] {issue.program}: {issue.message}", err=True)
        click.echo(f"\n{len(bundles)} program(s) would be synced.")
        return

    repo = _repo()
    results = []
    had_errors = False
    for b in bundles:
        prog_id, issues = sync_program(b, repo)
        for issue in issues:
            prefix = "ERROR" if issue.level == "error" else "WARN"
            click.echo(f"  [{prefix}] {b.program.name}: {issue.message}", err=True)
        if not prog_id:
            click.echo(f"  SKIPPED: {b.program.name}", err=True)
            had_errors = True
            continue
        trigs = f" +{len(b.triggers)} triggers" if b.triggers else ""
        click.echo(f"  synced: {b.program.name}{trigs}")
        results.append({"name": b.program.name, "id": prog_id, "type": b.program.program_type.value})

    click.echo(f"\n{len(results)} program(s) synced.")
    if ctx.obj["json"]:
        click.echo(json.dumps(results, indent=2))
    if had_errors:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════


@mind.group()
def task() -> None:
    """Manage tasks."""


@task.command("create")
@click.argument("name")
@click.option("--program", "program_name", default="do-content", help="Program name")
@click.option("--content", default="")
@click.option("--content-file", type=click.Path(exists=True))
@click.option("--description", "-d", default="")
@click.option("--priority", "-p", type=float, default=0.0)
@click.option("--runner", type=click.Choice(["lambda", "ecs"]), default=None)
@click.option("--clear-context", is_flag=True, default=False)
@click.option("--memory-keys", default="", help="Comma-separated memory keys")
@click.option("--tools", default="", help="Comma-separated tools")
@click.option("--resources", default="", help="Comma-separated extra resources")
@click.option("--parent", type=str, default=None, help="Parent task ID")
@click.option("--creator", default="cli")
@click.option("--disabled", is_flag=True, default=False, help="Create in DISABLED status")
@click.option("--limits", default="{}", help="JSON limits")
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def task_create(
    ctx: click.Context,
    name: str,
    program_name: str,
    content: str,
    content_file: str | None,
    description: str,
    priority: float,
    runner: str | None,
    clear_context: bool,
    memory_keys: str,
    tools: str,
    resources: str,
    parent: str | None,
    creator: str,
    disabled: bool,
    limits: str,
    metadata_json: str,
) -> None:
    """Create a task."""
    if content_file:
        content = Path(content_file).read_text()

    memory_keys_list = [s.strip() for s in memory_keys.split(",") if s.strip()] if memory_keys else []
    tools_list = [s.strip() for s in tools.split(",") if s.strip()] if tools else []
    resources_list = [s.strip() for s in resources.split(",") if s.strip()] if resources else []

    t = Task(
        name=name,
        program_name=program_name,
        content=content,
        description=description,
        priority=priority,
        runner=runner,
        clear_context=clear_context,
        memory_keys=memory_keys_list,
        tools=tools_list,
        resources=resources_list,
        parent_task_id=UUID(parent) if parent else None,
        creator=creator,
        status=TaskStatus.DISABLED if disabled else TaskStatus.RUNNABLE,
        limits=json.loads(limits),
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    task_id = repo.create_task(t)
    _output({"id": str(task_id), "name": name, "status": t.status.value}, use_json=ctx.obj["json"])


@task.command("list")
@click.option(
    "--status",
    type=click.Choice(["runnable", "running", "completed", "disabled"]),
    default=None,
)
@click.option("--limit", type=int, default=50)
@click.pass_context
def task_list(ctx: click.Context, status: str | None, limit: int) -> None:
    """List tasks."""
    repo = _repo()
    task_status = TaskStatus(status) if status else None
    tasks = repo.list_tasks(status=task_status, limit=limit)
    data = [
        {
            "id": str(t.id),
            "name": t.name,
            "status": t.status.value,
            "priority": t.priority,
            "program_name": t.program_name,
            "runner": t.runner,
            "creator": t.creator,
        }
        for t in tasks
    ]
    _output(data, use_json=ctx.obj["json"])


@task.command("show")
@click.argument("task_id")
@click.pass_context
def task_show(ctx: click.Context, task_id: str) -> None:
    """Show a task's details."""
    repo = _repo()
    t = repo.get_task(UUID(task_id))
    if not t:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)
    _output(t.model_dump(mode="json"), use_json=ctx.obj["json"])


@task.command("update")
@click.argument("task_id")
@click.option(
    "--status",
    type=click.Choice(["runnable", "running", "completed", "disabled"]),
    default=None,
)
@click.option("--priority", "-p", type=float, default=None)
@click.option("--content", default=None)
@click.option("--runner", type=click.Choice(["lambda", "ecs"]), default=None)
@click.pass_context
def task_update(
    ctx: click.Context,
    task_id: str,
    status: str | None,
    priority: float | None,
    content: str | None,
    runner: str | None,
) -> None:
    """Update a task."""
    repo = _repo()
    t = repo.get_task(UUID(task_id))
    if not t:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)

    updated: dict[str, object] = {"id": task_id}

    if status is not None:
        repo.update_task_status(UUID(task_id), TaskStatus(status))
        t.status = TaskStatus(status)
        updated["status"] = status

    if priority is not None:
        t.priority = priority
        updated["priority"] = priority

    if content is not None:
        t.content = content
        updated["content"] = "(updated)"

    if runner is not None:
        t.runner = runner
        updated["runner"] = runner

    # If any field besides status was changed, upsert the full task
    if any(k in updated for k in ("priority", "content", "runner")):
        repo.upsert_task(t, update_priority=True)

    _output(updated, use_json=ctx.obj["json"])


@task.command("disable")
@click.argument("task_id")
@click.pass_context
def task_disable(ctx: click.Context, task_id: str) -> None:
    """Disable a task (set status to DISABLED)."""
    repo = _repo()
    if repo.update_task_status(UUID(task_id), TaskStatus.DISABLED):
        _output({"id": task_id, "status": "disabled"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)


@task.command("enable")
@click.argument("task_id")
@click.pass_context
def task_enable(ctx: click.Context, task_id: str) -> None:
    """Enable a task (set status to RUNNABLE)."""
    repo = _repo()
    if repo.update_task_status(UUID(task_id), TaskStatus.RUNNABLE):
        _output({"id": task_id, "status": "runnable"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)


@task.command("load")
@click.argument("tasks_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--update-priority", is_flag=True, default=False, help="Update priority from file")
@click.option("--force", is_flag=True, default=False, help="Skip validation")
@click.pass_context
def task_load(ctx: click.Context, tasks_dir: str, update_priority: bool, force: bool) -> None:
    """Load tasks from a directory of .md, .yaml, .yml, and .py files."""
    from mind.task_loader import load_tasks_from_dir

    tasks_path = Path(tasks_dir)
    loaded_tasks = load_tasks_from_dir(tasks_path)

    if not loaded_tasks:
        click.echo("No tasks found.", err=True)
        sys.exit(1)

    repo = _repo()

    # Validation (unless --force)
    if not force:
        errors: list[str] = []
        for t in loaded_tasks:
            prog = repo.get_program(t.program_name)
            if not prog:
                errors.append(f"Task '{t.name}': program '{t.program_name}' not found")
            for key in t.memory_keys:
                mem = repo.query_memory(name=key, limit=1)
                if not mem:
                    errors.append(f"Task '{t.name}': memory key '{key}' not found")
        if errors:
            for err in errors:
                click.echo(f"ERROR: {err}", err=True)
            sys.exit(1)

    created = 0
    updated = 0

    for t in loaded_tasks:
        existing = repo.get_task_by_name(t.name)
        if existing:
            # Preserve status, creator, parent_task_id from existing
            t.status = existing.status
            t.creator = existing.creator
            t.parent_task_id = existing.parent_task_id
            repo.upsert_task(t, update_priority=update_priority)
            updated += 1
        else:
            repo.upsert_task(t, update_priority=True)
            created += 1

    result = {"created": created, "updated": updated, "total": created + updated}
    _output(result, use_json=ctx.obj["json"])


# ═══════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════


@mind.group()
def resource() -> None:
    """Manage resources."""


@resource.command("create")
@click.argument("name")
@click.option("--type", "resource_type", type=click.Choice(["pool", "consumable"]), required=True)
@click.option("--capacity", type=float, required=True)
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def resource_create(
    ctx: click.Context,
    name: str,
    resource_type: str,
    capacity: float,
    metadata_json: str,
) -> None:
    """Create or update a resource."""
    r = Resource(
        name=name,
        resource_type=ResourceType(resource_type),
        capacity=capacity,
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    repo.upsert_resource(r)
    _output({"name": name, "type": resource_type, "capacity": capacity, "status": "created"}, use_json=ctx.obj["json"])


@resource.command("list")
@click.pass_context
def resource_list(ctx: click.Context) -> None:
    """List all resources."""
    repo = _repo()
    resources = repo.list_resources()
    data = [
        {
            "name": r.name,
            "type": r.resource_type.value,
            "capacity": r.capacity,
        }
        for r in resources
    ]
    _output(data, use_json=ctx.obj["json"])


@resource.command("show")
@click.argument("name")
@click.pass_context
def resource_show(ctx: click.Context, name: str) -> None:
    """Show a resource's details and current usage."""
    repo = _repo()
    r = repo.get_resource(name)
    if not r:
        click.echo(f"Resource '{name}' not found.", err=True)
        sys.exit(1)

    data = r.model_dump(mode="json")

    if r.resource_type == ResourceType.POOL:
        usage = repo.get_pool_usage(name)
        data["current_usage"] = usage
        data["available"] = max(0, r.capacity - usage)
    else:
        usage = repo.get_consumable_usage(name)
        data["consumed"] = usage
        data["available"] = max(0.0, r.capacity - usage)

    _output(data, use_json=ctx.obj["json"])


@resource.command("delete")
@click.argument("name")
@click.pass_context
def resource_delete(ctx: click.Context, name: str) -> None:
    """Delete a resource."""
    repo = _repo()
    if repo.delete_resource(name):
        _output({"name": name, "status": "deleted"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Resource '{name}' not found.", err=True)
        sys.exit(1)


# ═══════════════════════════════════════════════════════════
# TRIGGERS
# ═══════════════════════════════════════════════════════════


@mind.group()
def trigger() -> None:
    """Manage triggers."""


@trigger.command("create")
@click.option("--program", "program_name", required=True)
@click.option("--pattern", required=True, help="Event pattern to match")
@click.option("--priority", type=int, default=10)
@click.pass_context
def trigger_create(ctx: click.Context, program_name: str, pattern: str, priority: int) -> None:
    """Create a trigger."""
    t = Trigger(
        program_name=program_name,
        event_pattern=pattern,
        priority=priority,
    )
    repo = _repo()
    trigger_id = repo.insert_trigger(t)
    _output(
        {"id": str(trigger_id), "program": program_name, "pattern": pattern, "status": "created"},
        use_json=ctx.obj["json"],
    )


@trigger.command("list")
@click.option("--program", "program_name", default=None)
@click.option("--all", "show_all", is_flag=True, help="Include disabled triggers")
@click.pass_context
def trigger_list(ctx: click.Context, program_name: str | None, show_all: bool) -> None:
    """List triggers."""
    repo = _repo()
    triggers = repo.list_triggers(enabled_only=not show_all, program_name=program_name)
    data = [
        {
            "id": str(t.id),
            "program": t.program_name,
            "pattern": t.event_pattern,
            "priority": t.priority,
            "enabled": t.enabled,
        }
        for t in triggers
    ]
    _output(data, use_json=ctx.obj["json"])


@trigger.command("enable")
@click.argument("trigger_id")
@click.pass_context
def trigger_enable(ctx: click.Context, trigger_id: str) -> None:
    """Enable a trigger."""
    repo = _repo()
    if repo.update_trigger_enabled(UUID(trigger_id), True):
        _output({"id": trigger_id, "enabled": True}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Trigger '{trigger_id}' not found.", err=True)
        sys.exit(1)


@trigger.command("disable")
@click.argument("trigger_id")
@click.pass_context
def trigger_disable(ctx: click.Context, trigger_id: str) -> None:
    """Disable a trigger."""
    repo = _repo()
    if repo.update_trigger_enabled(UUID(trigger_id), False):
        _output({"id": trigger_id, "enabled": False}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Trigger '{trigger_id}' not found.", err=True)
        sys.exit(1)


@trigger.command("delete")
@click.argument("trigger_id")
@click.pass_context
def trigger_delete(ctx: click.Context, trigger_id: str) -> None:
    """Delete a trigger."""
    repo = _repo()
    if repo.delete_trigger(UUID(trigger_id)):
        _output({"id": trigger_id, "status": "deleted"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Trigger '{trigger_id}' not found.", err=True)
        sys.exit(1)


# ═══════════════════════════════════════════════════════════
# CRON
# ═══════════════════════════════════════════════════════════


@mind.group()
def cron() -> None:
    """Manage cron schedules."""


@cron.command("create")
@click.option("--expression", required=True, help="Cron expression")
@click.option("--event", required=True, help="Event pattern to emit")
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def cron_create(ctx: click.Context, expression: str, event: str, metadata_json: str) -> None:
    """Create a cron schedule."""
    c = Cron(
        cron_expression=expression,
        event_pattern=event,
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    cron_id = repo.insert_cron(c)
    _output(
        {"id": str(cron_id), "expression": expression, "event": event, "status": "created"},
        use_json=ctx.obj["json"],
    )


@cron.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include disabled cron jobs")
@click.pass_context
def cron_list(ctx: click.Context, show_all: bool) -> None:
    """List cron schedules."""
    repo = _repo()
    crons = repo.list_cron(enabled_only=not show_all)
    data = [
        {
            "id": str(c.id),
            "expression": c.cron_expression,
            "event": c.event_pattern,
            "enabled": c.enabled,
        }
        for c in crons
    ]
    _output(data, use_json=ctx.obj["json"])


@cron.command("enable")
@click.argument("cron_id")
@click.pass_context
def cron_enable(ctx: click.Context, cron_id: str) -> None:
    """Enable a cron schedule."""
    repo = _repo()
    if repo.update_cron_enabled(UUID(cron_id), True):
        _output({"id": cron_id, "enabled": True}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Cron '{cron_id}' not found.", err=True)
        sys.exit(1)


@cron.command("disable")
@click.argument("cron_id")
@click.pass_context
def cron_disable(ctx: click.Context, cron_id: str) -> None:
    """Disable a cron schedule."""
    repo = _repo()
    if repo.update_cron_enabled(UUID(cron_id), False):
        _output({"id": cron_id, "enabled": False}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Cron '{cron_id}' not found.", err=True)
        sys.exit(1)


@cron.command("delete")
@click.argument("cron_id")
@click.pass_context
def cron_delete(ctx: click.Context, cron_id: str) -> None:
    """Delete a cron schedule."""
    repo = _repo()
    if repo.delete_cron(UUID(cron_id)):
        _output({"id": cron_id, "status": "deleted"}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Cron '{cron_id}' not found.", err=True)
        sys.exit(1)


# ═══════════════════════════════════════════════════════════
# EVENTS
# ═══════════════════════════════════════════════════════════


@mind.group()
def event() -> None:
    """View and send events."""


@event.command("list")
@click.option("--type", "event_type", default=None, help="Filter by event type")
@click.option("--limit", type=int, default=50)
@click.pass_context
def event_list(ctx: click.Context, event_type: str | None, limit: int) -> None:
    """List events."""
    repo = _repo()
    events = repo.get_events(event_type=event_type, limit=limit)
    data = [
        {
            "id": e.id,
            "type": e.event_type,
            "source": e.source,
            "payload": e.payload,
            "parent_event_id": e.parent_event_id,
            "created_at": str(e.created_at) if e.created_at else None,
        }
        for e in events
    ]
    _output(data, use_json=ctx.obj["json"])


@event.command("send")
@click.argument("event_type")
@click.option("--source", default="cli")
@click.option("--payload", default="{}", help="JSON payload")
@click.option("--parent", "parent_event_id", type=int, default=None, help="Parent event ID")
@click.pass_context
def event_send(
    ctx: click.Context,
    event_type: str,
    source: str,
    payload: str,
    parent_event_id: int | None,
) -> None:
    """Send (create) a new event."""
    ev = Event(
        event_type=event_type,
        source=source,
        payload=json.loads(payload),
        parent_event_id=parent_event_id,
    )
    repo = _repo()
    event_id = repo.append_event(ev)
    _output({"id": event_id, "type": event_type, "status": "sent"}, use_json=ctx.obj["json"])


@event.command("show")
@click.argument("event_id", type=int)
@click.pass_context
def event_show(ctx: click.Context, event_id: int) -> None:
    """Show an event and its descendants (causal tree)."""
    repo = _repo()
    events = repo.get_event_tree(event_id)
    if not events:
        click.echo(f"Event '{event_id}' not found.", err=True)
        sys.exit(1)
    data = [
        {
            "id": e.id,
            "type": e.event_type,
            "source": e.source,
            "payload": e.payload,
            "parent_event_id": e.parent_event_id,
            "created_at": str(e.created_at) if e.created_at else None,
        }
        for e in events
    ]
    _output(data, use_json=ctx.obj["json"])


@event.command("trace")
@click.argument("event_id", type=int)
@click.pass_context
def event_trace(ctx: click.Context, event_id: int) -> None:
    """Trace an event to its root and show the full causal tree."""
    repo = _repo()
    events = repo.get_event_root(event_id)
    if not events:
        click.echo(f"Event '{event_id}' not found.", err=True)
        sys.exit(1)
    data = [
        {
            "id": e.id,
            "type": e.event_type,
            "source": e.source,
            "payload": e.payload,
            "parent_event_id": e.parent_event_id,
            "created_at": str(e.created_at) if e.created_at else None,
        }
        for e in events
    ]
    _output(data, use_json=ctx.obj["json"])
