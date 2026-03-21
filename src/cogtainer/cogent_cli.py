"""CLI for managing cogents (create, destroy, list, status)."""

from __future__ import annotations

import click

from cogtainer.cogtainer_cli import _config_path
from cogtainer.config import (
    load_config,
    resolve_cogent_name,
    resolve_cogtainer_name,
)
from cogtainer.runtime.base import CogtainerRuntime
from cogtainer.runtime.factory import create_runtime


def _get_runtime() -> tuple[CogtainerRuntime, str]:
    """Load config, resolve cogtainer, create runtime.

    Returns (runtime, cogtainer_name).
    """
    cfg = load_config(_config_path())
    cogtainer_name = resolve_cogtainer_name(cfg)
    entry = cfg.cogtainers[cogtainer_name]
    runtime = create_runtime(entry, cogtainer_name=cogtainer_name)
    return runtime, cogtainer_name


@click.group()
def cli() -> None:
    """Manage cogents."""


@cli.command()
@click.argument("name")
def create(name: str) -> None:
    """Create a new cogent."""
    runtime, cogtainer_name = _get_runtime()
    runtime.create_cogent(name)
    click.echo(f"Created cogent '{name}' in cogtainer '{cogtainer_name}'.")


@cli.command()
@click.argument("name")
def destroy(name: str) -> None:
    """Destroy a cogent and all its data."""
    runtime, cogtainer_name = _get_runtime()

    if not click.confirm(f"Destroy cogent '{name}' in '{cogtainer_name}'?"):
        click.echo("Aborted.")
        return

    runtime.destroy_cogent(name)
    click.echo(f"Destroyed cogent '{name}'.")


@cli.command()
@click.argument("name", required=False)
def select(name: str | None) -> None:
    """Select a cogent by writing COGTAINER and COGENT to .env."""
    runtime, cogtainer_name = _get_runtime()
    cogents = runtime.list_cogents()

    if not cogents:
        click.echo(f"No cogents in cogtainer '{cogtainer_name}'.", err=True)
        raise SystemExit(1)

    if name is None:
        from cogtainer.cogtainer_cli import _pick

        name = _pick("cogent", sorted(cogents))

    if name not in cogents:
        click.echo(f"Cogent '{name}' not found in cogtainer '{cogtainer_name}'.", err=True)
        raise SystemExit(1)

    from cli.local_dev import write_repo_env

    env_path = write_repo_env({"COGTAINER": cogtainer_name, "COGENT": name})
    click.echo(f"Selected cogent '{name}' in cogtainer '{cogtainer_name}' (wrote {env_path})")


@cli.command("list")
def list_cmd() -> None:
    """List all cogents in the current cogtainer."""
    runtime, cogtainer_name = _get_runtime()
    cogents = runtime.list_cogents()

    if not cogents:
        click.echo(f"No cogents in cogtainer '{cogtainer_name}'.")
        return

    click.echo(f"Cogents in '{cogtainer_name}':")
    for name in cogents:
        click.echo(f"  {name}")


@cli.command()
@click.argument("name", required=False)
def status(name: str | None) -> None:
    """Show details for a cogent."""
    runtime, cogtainer_name = _get_runtime()

    if name is None:
        cogents = runtime.list_cogents()
        name = resolve_cogent_name(cogents)

    click.echo(f"Cogent: {name}")
    click.echo(f"  cogtainer: {cogtainer_name}")


if __name__ == "__main__":
    cli()
