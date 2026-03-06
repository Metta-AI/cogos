"""cogent <name> memory — manage hierarchical memory records."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click

from brain.db.models import MemoryScope
from cli import get_cogent_name


def _get_store():
    """Lazy import to avoid heavy imports at CLI load time."""
    from brain.db.repository import Repository
    from memory.store import MemoryStore

    repo = Repository.create()
    return MemoryStore(repo)


@click.group()
def memory():
    """Manage cogent memory records."""
    pass


@memory.command("create")
@click.pass_context
def create_cmd(ctx: click.Context):
    """Ensure memory schema is applied to the database via Data API."""
    from brain.db.migrations import apply_schema

    name = get_cogent_name(ctx)
    click.echo(f"Applying memory schema for cogent-{name}...")

    version = apply_schema()
    click.echo(f"Schema at version {version}.")


@memory.command("list")
@click.option("--prefix", "-p", default=None, help="Filter by name prefix")
@click.option("--scope", "-s", type=click.Choice(["cogent", "polis"]), default=None)
@click.option("--limit", "-n", default=200, help="Max records to return")
@click.pass_context
def list_cmd(ctx: click.Context, prefix: str | None, scope: str | None, limit: int):
    """List memory records."""
    get_cogent_name(ctx)  # validate cogent is set
    store = _get_store()

    scope_enum = MemoryScope(scope) if scope else None
    records = store.list_memories(prefix=prefix, scope=scope_enum, limit=limit)

    if not records:
        click.echo("No memory records found.")
        return

    for rec in records:
        preview = rec.content[:80].replace("\n", " ")
        if len(rec.content) > 80:
            preview += "..."
        scope_tag = rec.scope.value[0].upper()  # P or C
        click.echo(f"  [{scope_tag}] {rec.name or '(unnamed)'}  {preview}")

    click.echo(f"\n{len(records)} record(s)")


@memory.command("get")
@click.argument("name")
@click.pass_context
def get_cmd(ctx: click.Context, name: str):
    """Get a memory record by name."""
    get_cogent_name(ctx)  # validate cogent is set
    store = _get_store()

    record = store.get(name)
    if not record:
        raise click.ClickException(f"No memory record with name: {name}")

    click.echo(f"Name:    {record.name}")
    click.echo(f"Scope:   {record.scope.value}")
    click.echo(f"Updated: {record.updated_at}")
    click.echo("---")
    click.echo(record.content)


@memory.command("delete")
@click.argument("prefix")
@click.option("--scope", "-s", type=click.Choice(["cogent", "polis"]), default=None)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete_cmd(ctx: click.Context, prefix: str, scope: str | None, yes: bool):
    """Delete memory records matching a prefix."""
    get_cogent_name(ctx)  # validate cogent is set
    store = _get_store()

    scope_enum = MemoryScope(scope) if scope else None

    # Preview what will be deleted
    records = store.list_memories(prefix=prefix, scope=scope_enum)
    if not records:
        click.echo("No records match that prefix.")
        return

    click.echo(f"Will delete {len(records)} record(s):")
    for rec in records:
        click.echo(f"  [{rec.scope.value[0].upper()}] {rec.name}")

    if not yes:
        click.confirm("Continue?", abort=True)

    count = store.delete_by_prefix(prefix, scope=scope_enum)
    click.echo(f"Deleted {count} record(s).")


@memory.command("put")
@click.argument("path", type=click.Path(exists=True))
@click.option("--prefix", "-p", default="/", help="Mount point in the memory tree")
@click.option("--scope", "-s", type=click.Choice(["cogent", "polis"]), default="cogent")
@click.option("--no-embed", is_flag=True, help="Skip embedding generation")
@click.pass_context
def put_cmd(ctx: click.Context, path: str, prefix: str, scope: str, no_embed: bool):
    """Upsert memory records from .md files.

    PATH can be a directory (recursively walks .md files) or a single .md file.
    --prefix mounts files at a point in the memory tree.

    Examples:

        cogent dr.alpha memory put ./guides/ --prefix /mind/channels/discord
        cogent dr.alpha memory put ./tone.md --prefix /mind/policies
    """
    get_cogent_name(ctx)  # validate cogent is set
    store = _get_store()
    scope_enum = MemoryScope(scope)
    prefix = prefix.rstrip("/")

    source_path = Path(path)
    files: list[tuple[Path, str]] = []  # (file_path, memory_name)

    if source_path.is_file():
        name = prefix + "/" + source_path.stem
        files.append((source_path, name))
    elif source_path.is_dir():
        for md_file in sorted(source_path.rglob("*.md")):
            rel = md_file.relative_to(source_path)
            # Strip .md extension, join path parts with /
            name = prefix + "/" + str(rel.with_suffix("")).replace("\\", "/")
            files.append((md_file, name))
    else:
        raise click.ClickException(f"Path is neither file nor directory: {path}")

    if not files:
        click.echo("No .md files found.")
        return

    click.echo(f"Upserting {len(files)} memory record(s) into scope={scope}:")
    for file_path, mem_name in files:
        content = file_path.read_text()
        provenance = {
            "source": "cli:put",
            "file": str(file_path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        store.upsert(
            mem_name,
            content,
            scope=scope_enum,
            provenance=provenance,
            generate_embedding=not no_embed,
        )
        click.echo(f"  {mem_name}")

    click.echo(f"Done. {len(files)} record(s) upserted.")
