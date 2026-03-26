"""Shared CLI utilities."""

from __future__ import annotations

import click


def get_cogent_name(ctx: click.Context) -> str:
    """Return the cogent identifier from the root context."""
    obj = ctx.find_root().obj
    name = (obj.get("cogent_name") or obj.get("cogent_id")) if obj else None
    if not name:
        raise click.UsageError("No cogent specified. Set COGENT env var or default_cogent in ~/.cogos/config.yml")
    return name


class DefaultCommandGroup(click.Group):
    """Group that defaults to a given subcommand when none is provided."""

    def __init__(self, *args, default_cmd: str = "status", **kwargs):
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx, args):
        if not args or (args[0].startswith("-") and args[0] != "--help"):
            args = [self.default_cmd] + list(args)
        return super().parse_args(ctx, args)
