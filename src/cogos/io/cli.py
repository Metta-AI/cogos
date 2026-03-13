"""cogent channels — external communication channel management."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from polis.aws import DEFAULT_ORG_PROFILE, ORG_PROFILE_ENV

CHANNEL_TYPES = {
    "discord": "static",
    "github": "github_app",
    "asana": "static",
}

_PROFILE_HELP = f"AWS profile (default: ${ORG_PROFILE_ENV} or {DEFAULT_ORG_PROFILE})"


def _load_guide(channel_name: str) -> str | None:
    """Load the markdown guide for a channel."""
    # Look for guide.md in the channel's subdirectory
    path = Path(__file__).parent / channel_name / "guide.md"
    if path.exists():
        return path.read_text().strip()
    return None


@click.group()
def channels():
    """Manage cogent channels (GitHub, Discord, Asana)."""
    pass


@channels.command("list")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.argument("cogent_name")
def list_cmd(profile: str | None, cogent_name: str):
    """List provisioned channels for a cogent."""
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    sm = boto3.client("secretsmanager", region_name=region)
    prefix = f"identity_service/{cogent_name}/"

    try:
        paginator = sm.get_paginator("list_secrets")
        ch_list = []
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for s in page["SecretList"]:
                ch_list.append(s["Name"].removeprefix(prefix))
    except Exception as e:
        click.echo(f"Failed to list channels: {e}", err=True)
        sys.exit(1)

    if not ch_list:
        click.echo(f"No channels provisioned for '{cogent_name}'.")
        return

    click.echo(f"\nChannels for {cogent_name}:\n")
    for ch in sorted(ch_list):
        click.echo(f"  {ch}")


@channels.command()
@click.argument("channel_name", required=False)
@click.argument("cogent_name", required=False)
def create(channel_name: str | None, cogent_name: str | None):
    """Provision a channel for a cogent."""
    if not channel_name:
        click.echo("Available channels:\n")
        for ch, ctype in sorted(CHANNEL_TYPES.items()):
            guide_text = _load_guide(ch)
            title = guide_text.split("\n", 1)[0].lstrip("# ") if guide_text else ctype
            click.echo(f"  {ch:<12} {title}")
        click.echo("\nUsage: channels create <channel> <cogent-name>")
        return

    if not cogent_name:
        click.echo("Usage: channels create <channel> <cogent-name>", err=True)
        sys.exit(1)

    channel_type = CHANNEL_TYPES.get(channel_name)
    if not channel_type:
        click.echo(f"Unknown channel: {channel_name}")
        click.echo(f"Supported: {', '.join(CHANNEL_TYPES)}")
        sys.exit(1)

    guide_text = _load_guide(channel_name)
    if guide_text:
        click.echo()
        click.echo(guide_text)
        click.echo()

    click.echo(f"Channel type: {channel_type}")
    click.echo(f"TODO: Implement {channel_type} provisioning for {cogent_name}")


@channels.command()
@click.argument("channel_name")
@click.argument("cogent_name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def destroy(channel_name: str, cogent_name: str, yes: bool):
    """Remove a channel from a cogent."""
    import boto3

    if not yes:
        click.confirm(f"Delete {channel_name} channel for {cogent_name}?", abort=True)

    region = os.environ.get("AWS_REGION", "us-east-1")
    sm = boto3.client("secretsmanager", region_name=region)
    secret_id = f"identity_service/{cogent_name}/{channel_name}"

    try:
        sm.delete_secret(SecretId=secret_id, ForceDeleteWithoutRecovery=True)
        click.echo(f"Deleted {secret_id}.")
    except Exception as e:
        click.echo(f"Failed to delete {secret_id}: {e}", err=True)
        sys.exit(1)


@channels.command()
@click.argument("cogent_name")
def status(cogent_name: str):
    """Show provisioned channels and token status."""
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
        click.echo(f"Failed to list channels: {e}", err=True)
        sys.exit(1)

    if not secrets:
        click.echo(f"No channels provisioned for '{cogent_name}'.")
        return

    click.echo(f"\nChannels for {cogent_name}:\n")
    for s in sorted(secrets, key=lambda x: x["Name"]):
        ch_name = s["Name"].split("/")[-1]
        try:
            val = sm.get_secret_value(SecretId=s["Name"])
            data = json.loads(val["SecretString"])
            secret_type = data.get("type", "unknown")
            has_token = bool(data.get("access_token") or data.get("bot_token"))
            status_str = "ready" if has_token else "missing"
        except Exception:
            secret_type = "?"
            status_str = "error"
        click.echo(f"  {ch_name:<12} type={secret_type:<16} status={status_str}")


@channels.command()
@click.argument("channel_name")
@click.argument("cogent_name")
@click.option("--message", "-m", default="Hello, this is a test message.", help="Message content")
def send(channel_name: str, cogent_name: str, message: str):
    """Send a test message via a channel."""
    click.echo(f"Sending test message to {cogent_name} via {channel_name}...")
    click.echo(f"  message: {message}")
    click.echo()
    click.echo("TODO: Implement send for each channel type")


if __name__ == "__main__":
    channels()
