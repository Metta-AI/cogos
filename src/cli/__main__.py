import os
import sys

import click

from cli.dashboard import dashboard

# Known top-level commands — used to detect cogent name argument
_COMMANDS = {"dashboard", "brain", "memory", "mind", "--help", "-h"}


def _preprocess_argv() -> None:
    """Extract cogent name from argv before Click processes it.

    Supports: cogent <name> <command> [options]
    The first arg that isn't a known command or option is the cogent name.
    """
    args = sys.argv[1:]
    if args and not args[0].startswith("-") and args[0] not in _COMMANDS:
        os.environ["COGENT_ID"] = args[0]
        sys.argv = [sys.argv[0]] + args[1:]


@click.group()
@click.pass_context
def main(ctx: click.Context):
    """Cogent CLI.

    \b
    Usage: cogent <name> <command> [options]
    Example: cogent dr.alpha brain create
    """
    ctx.ensure_object(dict)
    if "COGENT_ID" in os.environ:
        ctx.obj["cogent_id"] = os.environ["COGENT_ID"]


main.add_command(dashboard)

# Brain infrastructure CLI
from brain.cli import brain  # noqa: E402

main.add_command(brain)

# Memory management CLI
from memory.cli import memory  # noqa: E402

main.add_command(memory)

# Mind management CLI
from mind.cli import mind  # noqa: E402

main.add_command(mind)


def entry():
    _preprocess_argv()
    main()


if __name__ == "__main__":
    entry()
