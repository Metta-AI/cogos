import os
import sys

import click

from cli.dashboard import dashboard
from cli.local_dev import apply_local_checkout_env
from polis.config import deploy_config

# Known top-level commands — used to detect cogent name argument
_COMMANDS = {"dashboard", "cogtainer", "memory", "run", "cogos", "status", "shell", "--help", "-h"}


def _preprocess_argv() -> None:
    """Extract cogent name from argv before Click processes it.

    Supports: cogent <name> <command> [options]
    The first arg that isn't a known command or option is the cogent name.
    """
    args = sys.argv[1:]
    if args and not args[0].startswith("-") and args[0] not in _COMMANDS:
        os.environ["COGENT_ID"] = args[0]
        if args[0] == "local":
            apply_local_checkout_env()
        sys.argv = [sys.argv[0]] + args[1:]


@click.group()
@click.pass_context
def main(ctx: click.Context):
    """Cogent CLI.

    \b
    Usage: cogent <name> <command> [options]
    Example: cogent my-cogent cogtainer create
    """
    ctx.ensure_object(dict)
    if "COGENT_ID" in os.environ:
        ctx.obj["cogent_id"] = os.environ["COGENT_ID"]


main.add_command(dashboard)

# Cogtainer infrastructure CLI
from cogtainer.cli import cogtainer  # noqa: E402

main.add_command(cogtainer)

# Memory management CLI
from memory.cli import memory  # noqa: E402

main.add_command(memory)

# Run management CLI
from run.cli import run  # noqa: E402

main.add_command(run)

# CogOS management CLI
from cogos.cli.__main__ import cogos  # noqa: E402

main.add_command(cogos)


@main.command("status")
@click.pass_context
def status(ctx: click.Context):
    """Show status of all subsystems for a cogent."""
    from cogtainer.cli import status_cmd as cogtainer_status
    from memory.cli import status_cmd as memory_status

    ctx.invoke(cogtainer_status)
    click.echo()
    ctx.invoke(memory_status)


@main.command("shell")
@click.pass_context
def shell_cmd(ctx: click.Context):
    """Interactive CogOS shell."""
    from cogos.shell import CogentShell

    cogent_name = ctx.obj.get("cogent_id") or deploy_config("default_cogent", "")
    if not cogent_name:
        raise click.UsageError("No cogent specified. Use: cogent <name> shell, set COGENT_ID, or set default_cogent in ~/.cogos/config.yml")
    CogentShell(cogent_name).run()


def entry():
    _preprocess_argv()
    main()


if __name__ == "__main__":
    entry()
