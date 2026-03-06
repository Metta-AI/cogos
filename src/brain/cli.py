"""cogent brain — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click

from cli import get_cogent_name  # noqa: F401 — re-export for back-compat


class DefaultCommandGroup(click.Group):
    """Group that defaults to a given subcommand when none is provided."""

    def __init__(self, *args, default_cmd: str = "status", **kwargs):
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx, args):
        if not args or (args[0].startswith("-") and args[0] != "--help"):
            args = [self.default_cmd] + list(args)
        return super().parse_args(ctx, args)


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

    # Fetch stack outputs + resources so memory schema can use Data API
    import os

    import boto3

    cf = boto3.client("cloudformation", region_name="us-east-1")
    try:
        resp = cf.describe_stacks(StackName=f"cogent-{safe_name}-brain")
        outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
        if "ClusterArn" in outputs:
            os.environ["DB_CLUSTER_ARN"] = outputs["ClusterArn"]
        if "SecretArn" in outputs:
            os.environ["DB_SECRET_ARN"] = outputs["SecretArn"]
        else:
            # SecretArn may not be an output yet — look it up from stack resources
            resources = cf.list_stack_resources(StackName=f"cogent-{safe_name}-brain")
            for r in resources.get("StackResourceSummaries", []):
                if "Secret" in r["LogicalResourceId"] and "Attachment" not in r["LogicalResourceId"]:
                    if r["PhysicalResourceId"].startswith("arn:aws:secretsmanager:"):
                        os.environ["DB_SECRET_ARN"] = r["PhysicalResourceId"]
                        break
    except Exception as e:
        click.echo(f"Warning: could not read stack outputs: {e}")

    # Apply memory schema
    click.echo("Applying memory schema...")
    ctx.invoke(_memory_create)


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

# Memory create command (invoked by brain create)
from memory.cli import create_cmd as _memory_create  # noqa: E402
