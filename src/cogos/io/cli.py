"""cogent io — external IO integration management."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from polis.aws import DEFAULT_ORG_PROFILE, ORG_PROFILE_ENV

IO_TYPES = {
    "discord": "static",
    "github": "github_app",
    "asana": "static",
}

_PROFILE_HELP = f"AWS profile (default: ${ORG_PROFILE_ENV} or {DEFAULT_ORG_PROFILE})"


def _load_guide(io_name: str) -> str | None:
    """Load the markdown guide for an IO integration."""
    path = Path(__file__).parent / io_name / "guide.md"
    if path.exists():
        return path.read_text().strip()
    return None


@click.group()
def io():
    """Manage cogent IO integrations (GitHub, Discord, Asana)."""
    pass


@io.command("list")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.argument("cogent_name")
def list_cmd(profile: str | None, cogent_name: str):
    """List provisioned IO integrations for a cogent."""
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    sm = boto3.client("secretsmanager", region_name=region)
    prefix = f"identity_service/{cogent_name}/"

    try:
        paginator = sm.get_paginator("list_secrets")
        io_list = []
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for s in page["SecretList"]:
                io_list.append(s["Name"].removeprefix(prefix))
    except Exception as e:
        click.echo(f"Failed to list IO integrations: {e}", err=True)
        sys.exit(1)

    if not io_list:
        click.echo(f"No IO integrations provisioned for '{cogent_name}'.")
        return

    click.echo(f"\nIO integrations for {cogent_name}:\n")
    for name in sorted(io_list):
        click.echo(f"  {name}")


@io.command()
@click.argument("io_name", required=False)
@click.argument("cogent_name", required=False)
def create(io_name: str | None, cogent_name: str | None):
    """Provision an IO integration for a cogent."""
    if not io_name:
        click.echo("Available IO integrations:\n")
        for name, itype in sorted(IO_TYPES.items()):
            guide_text = _load_guide(name)
            title = guide_text.split("\n", 1)[0].lstrip("# ") if guide_text else itype
            click.echo(f"  {name:<12} {title}")
        click.echo("\nUsage: io create <integration> <cogent-name>")
        return

    if not cogent_name:
        click.echo("Usage: io create <integration> <cogent-name>", err=True)
        sys.exit(1)

    io_type = IO_TYPES.get(io_name)
    if not io_type:
        click.echo(f"Unknown IO integration: {io_name}")
        click.echo(f"Supported: {', '.join(IO_TYPES)}")
        sys.exit(1)

    guide_text = _load_guide(io_name)
    if guide_text:
        click.echo()
        click.echo(guide_text)
        click.echo()

    click.echo(f"IO type: {io_type}")
    click.echo(f"TODO: Implement {io_type} provisioning for {cogent_name}")


@io.command()
@click.argument("io_name")
@click.argument("cogent_name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def destroy(io_name: str, cogent_name: str, yes: bool):
    """Remove an IO integration from a cogent."""
    import boto3

    if not yes:
        click.confirm(f"Delete {io_name} IO integration for {cogent_name}?", abort=True)

    region = os.environ.get("AWS_REGION", "us-east-1")
    sm = boto3.client("secretsmanager", region_name=region)
    secret_id = f"identity_service/{cogent_name}/{io_name}"

    try:
        sm.delete_secret(SecretId=secret_id, ForceDeleteWithoutRecovery=True)
        click.echo(f"Deleted {secret_id}.")
    except Exception as e:
        click.echo(f"Failed to delete {secret_id}: {e}", err=True)
        sys.exit(1)


@io.command()
@click.argument("cogent_name")
def status(cogent_name: str):
    """Show provisioned IO integrations and token status."""
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    sm = boto3.client("secretsmanager", region_name=region)
    prefix = f"identity_service/{cogent_name}/"

    try:
        paginator = sm.get_paginator("list_secrets")
        secrets = []
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for s in page["SecretList"]:
                secrets.append(s)
    except Exception as e:
        click.echo(f"Failed to list IO integrations: {e}", err=True)
        sys.exit(1)

    if not secrets:
        click.echo(f"No IO integrations provisioned for '{cogent_name}'.")
        return

    click.echo(f"\nIO integrations for {cogent_name}:\n")
    for s in sorted(secrets, key=lambda x: x["Name"]):
        io_name = s["Name"].split("/")[-1]
        try:
            val = sm.get_secret_value(SecretId=s["Name"])
            data = json.loads(val["SecretString"])
            secret_type = data.get("type", "unknown")
            has_token = bool(data.get("access_token") or data.get("bot_token"))
            status_str = "ready" if has_token else "missing"
        except Exception:
            secret_type = "?"
            status_str = "error"
        click.echo(f"  {io_name:<12} type={secret_type:<16} status={status_str}")


@io.command()
@click.argument("io_name")
@click.argument("cogent_name")
@click.option("--message", "-m", default="Hello, this is a test message.", help="Message content")
def send(io_name: str, cogent_name: str, message: str):
    """Send a test message via an IO integration."""
    click.echo(f"Sending test message to {cogent_name} via {io_name}...")
    click.echo(f"  message: {message}")
    click.echo()
    click.echo("TODO: Implement send for each IO type")


if __name__ == "__main__":
    io()
