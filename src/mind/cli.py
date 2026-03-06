"""Mind CLI — CRUD interface for programs, tasks, triggers, and cron.

All commands write to the brain's database via the Repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

import click

from cli import get_cogent_name
from brain.db.models import (
    Cron,
    Event,
    MemoryRecord,
    MemoryScope,
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
from brain.db.local_repository import LocalRepository
from brain.db.repository import Repository
from mind.loader import load_resources, sync_resources
from mind.program import load_program, load_programs_dir, sync_program, validate_bundle


def _ensure_db_env(cogent_name: str) -> None:
    """Set DB env vars from CloudFormation stack outputs in the polis account."""
    import os

    if os.environ.get("USE_LOCAL_DB") == "1":
        return

    from polis.aws import get_polis_session, set_profile

    safe_name = cogent_name.replace(".", "-")
    stack_name = f"cogent-{safe_name}-brain"

    try:
        set_profile("softmax-org")
        session, _ = get_polis_session()
    except Exception:
        return

    cf = session.client("cloudformation", region_name="us-east-1")

    try:
        resp = cf.describe_stacks(StackName=stack_name)
    except Exception:
        return
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}

    if "ClusterArn" in outputs:
        os.environ.setdefault("DB_RESOURCE_ARN", outputs["ClusterArn"])
        os.environ.setdefault("DB_CLUSTER_ARN", outputs["ClusterArn"])
    if "SecretArn" in outputs:
        os.environ.setdefault("DB_SECRET_ARN", outputs["SecretArn"])
    else:
        resources = cf.list_stack_resources(StackName=stack_name)
        for r in resources.get("StackResourceSummaries", []):
            if "Secret" in r["LogicalResourceId"] and "Attachment" not in r["LogicalResourceId"]:
                if r["PhysicalResourceId"].startswith("arn:aws:secretsmanager:"):
                    os.environ.setdefault("DB_SECRET_ARN", r["PhysicalResourceId"])
                    break
    os.environ.setdefault("DB_NAME", "cogent")

    # Export polis credentials so Repository's boto3 client can access RDS Data API
    creds = session.get_credentials().get_frozen_credentials()
    os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
    if creds.token:
        os.environ["AWS_SESSION_TOKEN"] = creds.token
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def _repo() -> Repository | LocalRepository:
    """Create a repository from environment variables.

    Set USE_LOCAL_DB=1 to use LocalRepository (JSON file) for local dev.
    Otherwise requires DB_RESOURCE_ARN, DB_SECRET_ARN, and DB_NAME.
    """
    import os

    if os.environ.get("USE_LOCAL_DB") == "1":
        return LocalRepository()
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
    import os

    ctx.ensure_object(dict)
    ctx.obj["json"] = use_json

    # Auto-discover DB ARNs from polis account so all subcommands use RDS
    if not (os.environ.get("DB_RESOURCE_ARN") or os.environ.get("DB_CLUSTER_ARN")):
        obj = ctx.find_root().obj
        name = (obj.get("cogent_id") if obj else None) or os.environ.get("COGENT_ID")
        if name:
            _ensure_db_env(name)


# ═══════════════════════════════════════════════════════════
# PROGRAMS
# ═══════════════════════════════════════════════════════════


_DEFAULT_EGG_DIR = "eggs/ovo"
_DEFAULT_PROGRAMS_DIR = "eggs/ovo/programs"
_DEFAULT_TASKS_DIR = "eggs/ovo/tasks"
_DEFAULT_MEMORIES_DIR = "eggs/ovo/memories"
_DEFAULT_RESOURCES_FILE = "eggs/ovo/resources.py"


@mind.command("status")
@click.pass_context
def mind_status(ctx: click.Context) -> None:
    """Show mind status: programs, tasks, triggers, cron, and resources."""
    from rich.console import Console
    from rich.table import Table

    from brain.db.models import ResourceType

    name = get_cogent_name(ctx)
    repo = _repo()
    console = Console()

    table = Table(title=f"Mind Status: {name}")
    table.add_column("Component", style="bold")
    table.add_column("Count")
    table.add_column("Details")

    # Programs
    programs = repo.list_programs()
    enabled = [p for p in programs if p.metadata.get("enabled", True)]
    disabled = [p for p in programs if not p.metadata.get("enabled", True)]
    table.add_row("Programs", str(len(programs)), f"{len(enabled)} enabled, {len(disabled)} disabled")

    # Tasks
    from brain.db.models import TaskStatus as TS

    for ts in (TS.RUNNABLE, TS.RUNNING, TS.COMPLETED, TS.DISABLED):
        tasks = repo.list_tasks(status=ts, limit=10000)
        label = f"Tasks ({ts.value})"
        table.add_row(label, str(len(tasks)), "")

    # Triggers
    triggers = repo.list_triggers(enabled_only=False)
    enabled_t = [t for t in triggers if t.enabled]
    table.add_row("Triggers", str(len(triggers)), f"{len(enabled_t)} enabled")

    # Cron
    crons = repo.list_cron(enabled_only=False)
    enabled_c = [c for c in crons if c.enabled]
    table.add_row("Cron", str(len(crons)), f"{len(enabled_c)} enabled")

    # Resources
    resources = repo.list_resources()
    for r in resources:
        if r.resource_type == ResourceType.POOL:
            usage = repo.get_pool_usage(r.name)
            avail = max(0, r.capacity - usage)
            table.add_row(f"Resource: {r.name}", f"{usage}/{r.capacity}", f"{avail} available (pool)")
        else:
            usage = repo.get_consumable_usage(r.name)
            avail = max(0.0, r.capacity - usage)
            table.add_row(f"Resource: {r.name}", f"{usage:.1f}/{r.capacity:.1f}", f"{avail:.1f} remaining (consumable)")

    console.print(table)


@mind.command("update")
@click.argument("egg_dir", default=_DEFAULT_EGG_DIR, type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Replace existing memory entries")
@click.pass_context
def mind_update(ctx: click.Context, egg_dir: str, force: bool) -> None:
    """Sync programs, tasks, and memories from an egg directory to the database.

    Default path: eggs/ovo/
    """
    import os

    from mind.memory_loader import load_memories_from_dir
    from mind.task_loader import load_tasks_from_dir

    egg = Path(egg_dir)
    repo = _repo()

    # 1. Resources
    res_file = egg / "resources.py"
    if res_file.is_file():
        synced_res = sync_resources(res_file, repo)
        click.echo(f"Resources: {len(synced_res)} synced")

    # 2. Programs
    programs_dir = egg / "programs"
    if programs_dir.is_dir():
        bundles = load_programs_dir(programs_dir)
        count = 0
        for b in bundles:
            prog_id, issues = sync_program(b, repo)
            for issue in issues:
                prefix = "ERROR" if issue.level == "error" else "WARN"
                click.echo(f"  [{prefix}] {b.program.name}: {issue.message}", err=True)
            if prog_id:
                count += 1
        click.echo(f"Programs: {count} synced")

    # 3. Tasks
    tasks_dir = egg / "tasks"
    if tasks_dir.is_dir():
        loaded_tasks = load_tasks_from_dir(tasks_dir)
        created = 0
        updated = 0
        for t in loaded_tasks:
            existing = repo.get_task_by_name(t.name)
            if existing:
                t.status = existing.status
                t.creator = existing.creator
                t.parent_task_id = existing.parent_task_id
                repo.upsert_task(t, update_priority=False)
                updated += 1
            else:
                repo.upsert_task(t, update_priority=True)
                created += 1
        click.echo(f"Tasks: {created} created, {updated} updated")

    # 4. Memories
    memories_dir = egg / "memories"
    if memories_dir.is_dir():
        memories = load_memories_from_dir(memories_dir)
        existing = {m.name: m for m in repo.query_memory(limit=10000)}
        added = 0
        for mem in memories:
            if mem.name in existing:
                if force:
                    repo.delete_memory(existing[mem.name].id)
                    repo.insert_memory(mem)
                    added += 1
            else:
                repo.insert_memory(mem)
                added += 1
        click.echo(f"Memories: {added} synced")

    # 5. Bootstrap (cron, triggers, bootstrap memory)
    bootstrap_file = egg / "bootstrap.py"
    if bootstrap_file.is_file():
        from mind.bootstrap_loader import sync_bootstrap
        counts = sync_bootstrap(bootstrap_file, repo)
        click.echo(
            f"Bootstrap: {counts['cron']} cron, "
            f"{counts['triggers']} triggers, "
            f"{counts['memory']} memory"
        )


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
@click.option("--resources", "resources_file", default=_DEFAULT_RESOURCES_FILE,
              type=click.Path(), help="Resources file to sync first")
@click.option("--no-resources", is_flag=True, help="Skip resource syncing")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing")
@click.pass_context
def program_update(
    ctx: click.Context, path: str, resources_file: str, no_resources: bool, dry_run: bool,
) -> None:
    """Sync programs from a directory (recursive .py/.md files).

    Loads resources first (from eggs/ovo/resources.py), then programs.
    Validates tools, checks memory includes, and registers triggers.
    Default path: eggs/ovo/programs/
    """
    root = Path(path)
    if not root.is_dir():
        click.echo(f"Not a directory: {root}", err=True)
        sys.exit(1)

    # ── Resources ──
    res_path = Path(resources_file)
    has_resources = not no_resources and res_path.is_file()
    if has_resources:
        try:
            res_list = load_resources(res_path)
        except ValueError as exc:
            click.echo(f"Resource load error: {exc}", err=True)
            sys.exit(1)

    # ── Programs ──
    bundles = load_programs_dir(root)
    if not bundles:
        click.echo(f"No .py or .md program files found under {root}", err=True)
        sys.exit(1)

    if dry_run:
        if has_resources:
            for r in res_list:
                click.echo(f"  resource: {r.name} ({r.resource_type.value}, capacity={r.capacity})")
            click.echo(f"  {len(res_list)} resource(s) would be synced.\n")
        all_issues: list = []
        for b in bundles:
            tool_issues = validate_bundle(b)
            all_issues.extend(tool_issues)
            trigs = f" +{len(b.triggers)} triggers" if b.triggers else ""
            click.echo(f"  {b.program.name} ({b.program.program_type.value}){trigs}")
        for issue in all_issues:
            prefix = "ERROR" if issue.level == "error" else "WARN"
            click.echo(f"  [{prefix}] {issue.program}: {issue.message}", err=True)
        click.echo(f"\n{len(bundles)} program(s) would be synced.")
        return

    repo = _repo()

    # Sync resources before programs
    if has_resources:
        synced_res = sync_resources(res_path, repo)
        for name in synced_res:
            click.echo(f"  resource: {name}")
        click.echo(f"  {len(synced_res)} resource(s) synced.\n")

    # Sync programs
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
@click.option("--program", "program_name", default="vsm/s1/do-content", help="Program name")
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
@click.option("--run", "run_now", is_flag=True, default=False, help="Send task:run event to trigger immediate execution")
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
    run_now: bool,
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

    if run_now:
        _send_task_run_event(ctx, repo, task_id)


def _send_task_run_event(ctx: click.Context, repo, task_id) -> None:
    """Send a task:run event to trigger immediate execution via EventBridge."""
    import os

    ev = Event(
        event_type="task:run",
        source="cli",
        payload={"task_id": str(task_id)},
    )
    event_id = repo.append_event(ev)

    bus_name = os.environ.get("EVENT_BUS_NAME")
    if not bus_name:
        obj = ctx.find_root().obj
        cogent_name = (obj.get("cogent_id") if obj else None) or os.environ.get("COGENT_ID")
        if cogent_name:
            bus_name = f"cogent-{cogent_name.replace('.', '-')}"

    if bus_name:
        from brain.lambdas.shared.events import put_event
        put_event(ev, bus_name)
        click.echo(f"Sent task:run event (id={event_id}) to {bus_name}")
    else:
        click.echo(f"Warning: task:run event stored (id={event_id}) but no EventBridge bus found")


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
    """Load tasks from a directory of .md, .yaml, .yml, and .py files.

    Validates programs exist, tools are valid, and memory keys are present.
    """
    from mind.task_loader import load_tasks_from_dir, validate_task

    tasks_path = Path(tasks_dir)
    loaded_tasks = load_tasks_from_dir(tasks_path)

    if not loaded_tasks:
        click.echo("No tasks found.", err=True)
        sys.exit(1)

    repo = _repo()

    # Validation (unless --force)
    if not force:
        all_issues = []
        for t in loaded_tasks:
            all_issues.extend(validate_task(t, repo))
        errors = [i for i in all_issues if i.level == "error"]
        for issue in all_issues:
            prefix = "ERROR" if issue.level == "error" else "WARN"
            click.echo(f"  [{prefix}] {issue.name}: {issue.message}", err=True)
        if errors:
            sys.exit(1)

    created = 0
    updated = 0

    for t in loaded_tasks:
        existing = repo.get_task_by_name(t.name)
        if existing:
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


@resource.command("list")
@click.pass_context
def resource_list(ctx: click.Context) -> None:
    """List all resources with current usage."""
    repo = _repo()
    resources = repo.list_resources()
    data = []
    for r in resources:
        entry: dict = {
            "name": r.name,
            "type": r.resource_type.value,
            "capacity": r.capacity,
        }
        if r.resource_type == ResourceType.POOL:
            usage = repo.get_pool_usage(r.name)
            entry["usage"] = usage
            entry["available"] = max(0, r.capacity - usage)
        else:
            usage = repo.get_consumable_usage(r.name)
            entry["consumed"] = usage
            entry["available"] = max(0.0, r.capacity - usage)
        data.append(entry)
    _output(data, use_json=ctx.obj["json"])


@resource.command("add")
@click.argument("name")
@click.option("--type", "resource_type", type=click.Choice(["pool", "consumable"]), required=True)
@click.option("--capacity", type=float, required=True)
@click.option("--metadata", "metadata_json", default="{}", help="JSON metadata")
@click.pass_context
def resource_add(
    ctx: click.Context,
    name: str,
    resource_type: str,
    capacity: float,
    metadata_json: str,
) -> None:
    """Add or update a single resource."""
    r = Resource(
        name=name,
        resource_type=ResourceType(resource_type),
        capacity=capacity,
        metadata=json.loads(metadata_json),
    )
    repo = _repo()
    repo.upsert_resource(r)
    _output({"name": name, "type": resource_type, "capacity": capacity, "status": "added"}, use_json=ctx.obj["json"])


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


@resource.command("update")
@click.argument("path", default=_DEFAULT_RESOURCES_FILE, type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Show what would change without writing")
@click.pass_context
def resource_update(ctx: click.Context, path: str, dry_run: bool) -> None:
    """Sync resources from a .py file (default: eggs/ovo/resources.py)."""
    res_path = Path(path)
    try:
        res_list = load_resources(res_path)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not res_list:
        click.echo("No resources found.", err=True)
        sys.exit(1)

    if dry_run:
        for r in res_list:
            click.echo(f"  {r.name} ({r.resource_type.value}, capacity={r.capacity})")
        click.echo(f"\n{len(res_list)} resource(s) would be synced.")
        return

    synced = sync_resources(res_path, _repo())
    for name in synced:
        click.echo(f"  synced: {name}")
    click.echo(f"\n{len(synced)} resource(s) synced.")
    if ctx.obj["json"]:
        click.echo(json.dumps([{"name": n} for n in synced], indent=2))


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
    """Send (create) a new event.

    Stores the event in the database AND publishes to EventBridge.
    Requires COGENT_ID (or cogent context) to derive the EventBridge bus name.
    """
    import os

    ev = Event(
        event_type=event_type,
        source=source,
        payload=json.loads(payload),
        parent_event_id=parent_event_id,
    )
    repo = _repo()
    event_id = repo.append_event(ev)

    # Publish to EventBridge
    bus_name = os.environ.get("EVENT_BUS_NAME")
    if not bus_name:
        obj = ctx.find_root().obj
        cogent_name = (obj.get("cogent_id") if obj else None) or os.environ.get("COGENT_ID")
        if cogent_name:
            safe_name = cogent_name.replace(".", "-")
            bus_name = f"cogent-{safe_name}"

    if bus_name:
        from brain.lambdas.shared.events import put_event
        put_event(ev, bus_name)

    _output({"id": event_id, "type": event_type, "bus": bus_name, "status": "sent"}, use_json=ctx.obj["json"])


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


# ── Memory ──────────────────────────────────────────────────


@mind.group()
def memory() -> None:
    """Manage memory entries."""


@memory.command("list")
@click.option("--scope", type=click.Choice(["cogent", "polis"]), default=None, help="Filter by scope")
@click.option("--prefix", default=None, help="Filter by name prefix")
@click.option("--limit", type=int, default=200)
@click.pass_context
def memory_list(ctx: click.Context, scope: str | None, prefix: str | None, limit: int) -> None:
    """List memory entries."""
    repo = _repo()
    mem_scope = MemoryScope(scope) if scope else None
    records = repo.query_memory(scope=mem_scope, name_prefix=prefix, limit=limit)
    data = [
        {
            "id": str(m.id),
            "scope": m.scope.value if m.scope else None,
            "name": m.name,
            "content": m.content[:120] + ("..." if len(m.content) > 120 else ""),
            "created_at": str(m.created_at) if m.created_at else None,
        }
        for m in records
    ]
    _output(data, use_json=ctx.obj["json"])


@memory.command("add")
@click.argument("name")
@click.argument("content")
@click.option("--scope", type=click.Choice(["cogent", "polis"]), default="cogent")
@click.option("--provenance", "provenance_json", default="{}", help="JSON provenance")
@click.pass_context
def memory_add(ctx: click.Context, name: str, content: str, scope: str, provenance_json: str) -> None:
    """Add a memory entry."""
    mem = MemoryRecord(
        scope=MemoryScope(scope),
        name=name,
        content=content,
        provenance=json.loads(provenance_json),
    )
    repo = _repo()
    mid = repo.insert_memory(mem)
    _output({"id": str(mid), "name": name, "scope": scope, "status": "added"}, use_json=ctx.obj["json"])


@memory.command("show")
@click.argument("memory_id")
@click.pass_context
def memory_show(ctx: click.Context, memory_id: str) -> None:
    """Show a memory entry."""
    repo = _repo()
    m = repo.get_memory(UUID(memory_id))
    if not m:
        click.echo(f"Memory '{memory_id}' not found.", err=True)
        sys.exit(1)
    _output_single({
        "id": str(m.id),
        "scope": m.scope.value if m.scope else None,
        "name": m.name,
        "content": m.content,
        "provenance": m.provenance,
        "created_at": str(m.created_at) if m.created_at else None,
        "updated_at": str(m.updated_at) if m.updated_at else None,
    })


@memory.command("delete")
@click.argument("memory_id")
@click.pass_context
def memory_delete(ctx: click.Context, memory_id: str) -> None:
    """Delete a memory entry."""
    repo = _repo()
    if not repo.delete_memory(UUID(memory_id)):
        click.echo(f"Memory '{memory_id}' not found.", err=True)
        sys.exit(1)
    _output({"id": memory_id, "status": "deleted"}, use_json=ctx.obj["json"])


@memory.command("load")
@click.argument("memories_dir", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Replace existing entries with same name")
@click.pass_context
def memory_load(ctx: click.Context, memories_dir: str, force: bool) -> None:
    """Load memory entries from a directory of .md and .yaml files."""
    from mind.memory_loader import load_memories_from_dir

    repo = _repo()
    memories = load_memories_from_dir(Path(memories_dir))

    existing = {m.name: m for m in repo.query_memory(limit=10000)}
    added = 0
    skipped = 0
    replaced = 0

    for mem in memories:
        if mem.name in existing:
            if force:
                repo.delete_memory(existing[mem.name].id)
                repo.insert_memory(mem)
                replaced += 1
            else:
                skipped += 1
        else:
            repo.insert_memory(mem)
            added += 1

    _output(
        {"added": added, "replaced": replaced, "skipped": skipped, "total": len(memories)},
        use_json=ctx.obj["json"],
    )
