"""cogent memory — manage versioned memory records."""

from __future__ import annotations

from pathlib import Path

import click


def _get_store():
    """Lazy import to avoid heavy imports at CLI load time."""
    from brain.db.repository import Repository
    from memory.store import MemoryStore

    repo = Repository.create()
    return MemoryStore(repo)


def _handle_errors(fn):
    """Decorator to convert MemoryReadOnlyError / ValueError to ClickException."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from memory.errors import MemoryReadOnlyError

        try:
            return fn(*args, **kwargs)
        except MemoryReadOnlyError as exc:
            raise click.ClickException(str(exc)) from exc
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper


@click.group()
def memory():
    """Manage cogent memory records."""


@memory.command("status")
@_handle_errors
def status_cmd():
    """Show memory count, count by source, and read-only stats."""
    store = _get_store()
    records = store.list_memories(limit=100_000)

    if not records:
        click.echo("No memory records.")
        return

    total = len(records)
    by_source: dict[str, int] = {}
    ro_count = 0

    for mem in records:
        mv = mem.versions.get(mem.active_version)
        if mv:
            by_source[mv.source] = by_source.get(mv.source, 0) + 1
            if mv.read_only:
                ro_count += 1

    click.echo(f"Total memories: {total}")
    click.echo()
    click.echo("By source:")
    for src, cnt in sorted(by_source.items()):
        click.echo(f"  {src}: {cnt}")
    click.echo()
    click.echo(f"Read-only: {ro_count}")


@memory.command("list")
@click.option("--prefix", "-p", default=None, help="Filter by name prefix")
@click.option("--source", "-s", default=None, help="Filter by source")
@click.option("--limit", "-n", default=200, help="Max records to return")
@_handle_errors
def list_cmd(prefix: str | None, source: str | None, limit: int):
    """List memory records."""
    store = _get_store()
    records = store.list_memories(prefix=prefix, source=source, limit=limit)

    if not records:
        click.echo("No memory records found.")
        return

    # Header
    click.echo(f"{'name':<40} {'v':>3} {'source':<10} {'ro':<4} preview")
    click.echo("-" * 100)

    for mem in records:
        mv = mem.versions.get(mem.active_version)
        source_val = mv.source if mv else ""
        ro_val = "Y" if (mv and mv.read_only) else ""
        content = mv.content if mv else ""
        preview = content[:60].replace("\n", " ")
        click.echo(
            f"{mem.name:<40} {mem.active_version:>3} {source_val:<10} {ro_val:<4} {preview}"
        )

    click.echo(f"\n{len(records)} record(s)")


@memory.command("get")
@click.argument("name")
@click.option("--version", "-v", "version_num", type=int, default=None, help="Show specific version")
@_handle_errors
def get_cmd(name: str, version_num: int | None):
    """Show full content of a memory record."""
    store = _get_store()

    if version_num is not None:
        mv = store.get_version(name, version_num)
        if mv is None:
            raise click.ClickException(
                f"Version {version_num} not found for memory '{name}'"
            )
        click.echo(f"Name:           {name}")
        click.echo(f"Version:        {mv.version}")
        click.echo(f"Source:         {mv.source}")
        click.echo(f"Read-only:      {mv.read_only}")
        click.echo(f"Created:        {mv.created_at}")
        click.echo("---")
        click.echo(mv.content)
    else:
        mem = store.get(name)
        if mem is None:
            raise click.ClickException(f"No memory record with name: {name}")

        mv = mem.versions.get(mem.active_version)
        click.echo(f"Name:           {mem.name}")
        click.echo(f"Active version: {mem.active_version}")
        if mv:
            click.echo(f"Source:         {mv.source}")
            click.echo(f"Read-only:      {mv.read_only}")
            click.echo(f"Created:        {mv.created_at}")
        click.echo("---")
        click.echo(mv.content if mv else "")


@memory.command("history")
@click.argument("name")
@_handle_errors
def history_cmd(name: str):
    """List all versions of a memory record."""
    store = _get_store()

    mem = store.get(name)
    if mem is None:
        raise click.ClickException(f"No memory record with name: {name}")

    versions = store.history(name)
    if not versions:
        click.echo("No versions found.")
        return

    click.echo(f"History for: {name}")
    click.echo(f"{'v':>4} {'source':<10} {'ro':<4} {'created_at':<26} preview")
    click.echo("-" * 100)

    for mv in versions:
        active_marker = "*" if mv.version == mem.active_version else " "
        preview = mv.content[:60].replace("\n", " ")
        ro_val = "Y" if mv.read_only else ""
        created = str(mv.created_at) if mv.created_at else ""
        click.echo(
            f"{active_marker}{mv.version:>3} {mv.source:<10} {ro_val:<4} {created:<26} {preview}"
        )


@memory.command("put")
@click.argument("path", type=click.Path(exists=True))
@click.option("--prefix", "-p", default="/", help="Mount point in the memory tree")
@click.option("--source", "-s", default="cogent", help="Source tag for versions")
@click.option("--force", "-f", is_flag=True, help="Force new version (bypasses read-only)")
@_handle_errors
def put_cmd(path: str, prefix: str, source: str, force: bool):
    """Upsert memory records from .md files.

    PATH can be a directory (recursively walks .md files) or a single .md file.
    --prefix mounts files at a point in the memory tree.

    With --force, uses new_version() which bypasses read-only checks.
    """
    store = _get_store()
    prefix = prefix.rstrip("/")

    source_path = Path(path)
    files: list[tuple[Path, str]] = []

    if source_path.is_file():
        name = prefix + "/" + source_path.stem
        files.append((source_path, name))
    elif source_path.is_dir():
        for md_file in sorted(source_path.rglob("*.md")):
            rel = md_file.relative_to(source_path)
            name = prefix + "/" + str(rel.with_suffix("")).replace("\\", "/")
            files.append((md_file, name))
    else:
        raise click.ClickException(f"Path is neither file nor directory: {path}")

    if not files:
        click.echo("No .md files found.")
        return

    click.echo(f"Upserting {len(files)} memory record(s) (source={source}):")
    created = 0
    updated = 0
    unchanged = 0

    for file_path, mem_name in files:
        content = file_path.read_text()
        if force:
            result = store.new_version(mem_name, content, source=source)
            if result is None:
                # Memory doesn't exist or content unchanged
                # Try create if it doesn't exist
                existing = store.get(mem_name)
                if existing is None:
                    store.create(mem_name, content, source=source)
                    click.echo(f"  + {mem_name}")
                    created += 1
                else:
                    click.echo(f"  = {mem_name} (unchanged)")
                    unchanged += 1
            else:
                click.echo(f"  ~ {mem_name} (v{result.version})")
                updated += 1
        else:
            from brain.db.models import Memory, MemoryVersion

            result = store.upsert(mem_name, content, source=source)
            if result is None:
                click.echo(f"  = {mem_name} (unchanged)")
                unchanged += 1
            elif isinstance(result, Memory):
                click.echo(f"  + {mem_name}")
                created += 1
            elif isinstance(result, MemoryVersion):
                click.echo(f"  ~ {mem_name} (v{result.version})")
                updated += 1

    click.echo(f"\nDone. {created} created, {updated} updated, {unchanged} unchanged.")


@memory.command("activate")
@click.argument("name")
@click.argument("version", type=int)
@_handle_errors
def activate_cmd(name: str, version: int):
    """Switch the active version of a memory."""
    store = _get_store()
    store.activate(name, version)
    click.echo(f"Activated version {version} for memory '{name}'.")


@memory.command("set-ro")
@click.argument("name")
@click.option("--version", "-v", "version_num", type=int, default=None, help="Target version (default: active)")
@click.option("--off", is_flag=True, help="Remove read-only flag")
@_handle_errors
def set_ro_cmd(name: str, version_num: int | None, off: bool):
    """Set or remove read-only flag on a memory version."""
    store = _get_store()
    read_only = not off
    store.set_read_only(name, read_only, version=version_num)
    state = "writable" if off else "read-only"
    ver_msg = f" version {version_num}" if version_num is not None else ""
    click.echo(f"Memory '{name}'{ver_msg} is now {state}.")


@memory.command("rename")
@click.argument("old")
@click.argument("new")
@_handle_errors
def rename_cmd(old: str, new: str):
    """Rename a memory record."""
    store = _get_store()
    store.rename(old, new)
    click.echo(f"Renamed '{old}' -> '{new}'.")


@memory.command("delete")
@click.argument("name")
@click.option("--version", "-v", "version_num", type=int, default=None, help="Delete specific version only")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@_handle_errors
def delete_cmd(name: str, version_num: int | None, yes: bool):
    """Delete a memory or a specific version."""
    store = _get_store()

    if version_num is not None:
        store.delete(name, version=version_num)
        click.echo(f"Deleted version {version_num} of memory '{name}'.")
    else:
        mem = store.get(name)
        if mem is None:
            raise click.ClickException(f"No memory record with name: {name}")

        mv = mem.versions.get(mem.active_version)
        preview = ""
        if mv:
            preview = mv.content[:80].replace("\n", " ")

        if not yes:
            click.echo(f"Memory: {name}")
            click.echo(f"Active version: {mem.active_version}")
            click.echo(f"Total versions: {len(mem.versions)}")
            if preview:
                click.echo(f"Preview: {preview}")
            click.confirm("Delete this memory?", abort=True)

        store.delete(name)
        click.echo(f"Deleted memory '{name}'.")
