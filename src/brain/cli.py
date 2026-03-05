"""cogent brain — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click


class DefaultCommandGroup(click.Group):
    """Group that defaults to a given subcommand when none is provided."""

    def __init__(self, *args, default_cmd: str = "status", **kwargs):
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx, args):
        if not args or (args[0].startswith("-") and args[0] != "--help"):
            args = [self.default_cmd] + list(args)
        return super().parse_args(ctx, args)


def get_cogent_name(ctx: click.Context) -> str:
    """Return the cogent name from the root context."""
    obj = ctx.find_root().obj
    name = obj.get("cogent_name") if obj else None
    if not name:
        raise click.UsageError("No cogent specified. Use: cogent <name> <command> or set COGENT_NAME env var.")
    return name


@click.group(cls=DefaultCommandGroup, default_cmd="status")
def brain():
    """Manage cogent infrastructure, ECS, and Lambda components."""
    pass


@brain.command("status")
@click.pass_context
def status_cmd(ctx: click.Context):
    """Show infrastructure status for a cogent."""
    name = get_cogent_name(ctx)
    click.echo(f"Status for cogent-{name}: not yet implemented (needs body.aws)")


@brain.command("create")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--watch", "-w", is_flag=True, help="Wait for stack to complete")
@click.pass_context
def create_cmd(ctx: click.Context, profile: str, watch: bool):
    """Deploy a cogent's brain infrastructure via CDK."""
    import subprocess

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    click.echo(f"Deploying brain infrastructure for cogent-{name}...")
    cmd = [
        "cdk",
        "deploy",
        f"cogent-{safe_name}-brain",
        "-c",
        f"cogent_name={name}",
        "--app",
        "python -m brain.cdk.app",
        "--require-approval",
        "never",
    ]
    if not watch:
        cmd.append("--no-rollback")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")
    click.echo(f"Brain infrastructure for cogent-{name} deployed.")


@brain.command("destroy")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def destroy_cmd(ctx: click.Context, profile: str, yes: bool):
    """Destroy a cogent's brain infrastructure via CDK."""
    import subprocess

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    if not yes:
        click.confirm(f"This will destroy the stack for cogent-{name}. Continue?", abort=True)
    cmd = [
        "cdk",
        "destroy",
        f"cogent-{safe_name}-brain",
        "-c",
        f"cogent_name={name}",
        "--app",
        "python -m brain.cdk.app",
        "--force",
    ]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise click.ClickException("CDK destroy failed")
    click.echo(f"Brain infrastructure for cogent-{name} destroyed.")


# Wire in update subcommands
from brain.update_cli import update  # noqa: E402

brain.add_command(update)
