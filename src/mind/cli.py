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
    Task,
    TaskStatus,
    Trigger,
    TriggerConfig,
)
from brain.db.repository import Repository


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


@mind.group()
def program() -> None:
    """Manage programs."""


@program.command("create")
@click.argument("name")
@click.option("--type", "program_type", type=click.Choice(["prompt", "python"]), default="prompt")
@click.option("--content", default="")
@click.option("--content-file", type=click.Path(exists=True))
@click.option("--includes", default="", help="Comma-separated memory keys")
@click.option("--tools", default="", help="Comma-separated mind CLI commands")
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def program_create(
    ctx: click.Context,
    name: str,
    program_type: str,
    content: str,
    content_file: str | None,
    includes: str,
    tools: str,
    metadata_json: str,
) -> None:
    """Create or update a program."""
    if content_file:
        content = Path(content_file).read_text()

    includes_list = [s.strip() for s in includes.split(",") if s.strip()] if includes else []
    tools_list = [s.strip() for s in tools.split(",") if s.strip()] if tools else []

    prog = Program(
        name=name,
        program_type=ProgramType(program_type),
        content=content,
        includes=includes_list,
        tools=tools_list,
        metadata=json.loads(metadata_json),
    )

    repo = _repo()
    prog_id = repo.upsert_program(prog)
    _output({"id": str(prog_id), "name": name, "status": "created"}, use_json=ctx.obj["json"])


@program.command("list")
@click.pass_context
def program_list(ctx: click.Context) -> None:
    """List all programs."""
    repo = _repo()
    programs = repo.list_programs()
    data = [
        {"name": p.name, "type": p.program_type.value, "includes": p.includes, "tools": p.tools}
        for p in programs
    ]
    _output(data, use_json=ctx.obj["json"])


@program.command("show")
@click.argument("name")
@click.pass_context
def program_show(ctx: click.Context, name: str) -> None:
    """Show a program's details."""
    repo = _repo()
    prog = repo.get_program(name)
    if not prog:
        click.echo(f"Program '{name}' not found.", err=True)
        sys.exit(1)
    _output(prog.model_dump(mode="json"), use_json=ctx.obj["json"])


@program.command("update")
@click.argument("name")
@click.option("--content", default=None)
@click.option("--content-file", type=click.Path(exists=True))
@click.option("--includes", default=None, help="Comma-separated memory keys")
@click.option("--tools", default=None, help="Comma-separated mind CLI commands")
@click.option("--metadata", "metadata_json", default=None, help="JSON metadata")
@click.pass_context
def program_update(
    ctx: click.Context,
    name: str,
    content: str | None,
    content_file: str | None,
    includes: str | None,
    tools: str | None,
    metadata_json: str | None,
) -> None:
    """Update an existing program."""
    repo = _repo()
    prog = repo.get_program(name)
    if not prog:
        click.echo(f"Program '{name}' not found.", err=True)
        sys.exit(1)

    if content_file:
        prog.content = Path(content_file).read_text()
    elif content is not None:
        prog.content = content

    if includes is not None:
        prog.includes = [s.strip() for s in includes.split(",") if s.strip()]
    if tools is not None:
        prog.tools = [s.strip() for s in tools.split(",") if s.strip()]
    if metadata_json is not None:
        prog.metadata = json.loads(metadata_json)

    repo.upsert_program(prog)
    _output({"name": name, "status": "updated"}, use_json=ctx.obj["json"])


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


# ═══════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════


@mind.group()
def task() -> None:
    """Manage tasks."""


@task.command("create")
@click.argument("name")
@click.option("--description", "-d", default="")
@click.option("--priority", "-p", type=int, default=0)
@click.option("--parent", type=str, default=None, help="Parent task ID")
@click.option("--creator", default="cli")
@click.option("--source-event", default=None)
@click.option("--limits", default="{}", help="JSON limits: {tokens, attempts, time_seconds}")
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def task_create(
    ctx: click.Context,
    name: str,
    description: str,
    priority: int,
    parent: str | None,
    creator: str,
    source_event: str | None,
    limits: str,
    metadata_json: str,
) -> None:
    """Create a task."""
    t = Task(
        name=name,
        description=description,
        priority=priority,
        parent_task_id=UUID(parent) if parent else None,
        creator=creator,
        source_event=source_event,
        limits=json.loads(limits),
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    task_id = repo.create_task(t)
    _output({"id": str(task_id), "name": name, "status": "created"}, use_json=ctx.obj["json"])


@task.command("list")
@click.option("--status", type=click.Choice(["pending", "running", "failed", "completed"]), default=None)
@click.option("--limit", type=int, default=50)
@click.pass_context
def task_list(ctx: click.Context, status: str | None, limit: int) -> None:
    """List tasks."""
    repo = _repo()
    task_status = TaskStatus(status) if status else None
    tasks = repo.list_tasks(status=task_status, limit=limit)
    data = [
        {"id": str(t.id), "name": t.name, "status": t.status.value, "priority": t.priority, "creator": t.creator}
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
@click.option("--status", type=click.Choice(["pending", "running", "failed", "completed"]), required=True)
@click.pass_context
def task_update(ctx: click.Context, task_id: str, status: str) -> None:
    """Update a task's status."""
    repo = _repo()
    if repo.update_task_status(UUID(task_id), TaskStatus(status)):
        _output({"id": task_id, "status": status}, use_json=ctx.obj["json"])
    else:
        click.echo(f"Task '{task_id}' not found.", err=True)
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
