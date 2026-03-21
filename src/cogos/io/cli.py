"""cogent io — external IO integration management."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

IO_TYPES = {
    "discord": "static",
    "github": "github_app",
    "asana": "static",
    "email": "cloudflare_ses",
    "claude-code": "mcp_channel",
}

_DEFAULT_ORG_PROFILE = os.environ.get("AWS_ORG_PROFILE", "softmax-org")
_PROFILE_HELP = f"AWS profile (default: $AWS_ORG_PROFILE or {_DEFAULT_ORG_PROFILE})"


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
    from cogtainer.secrets import create_secrets_provider

    prefix = f"identity_service/{cogent_name}/"

    try:
        provider = create_secrets_provider(provider_type="aws")
        keys = provider.list_secrets(prefix)
        io_list = [k.removeprefix(prefix) for k in keys]
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

    if io_type == "cloudflare_ses":
        from cogos.io.email.provision import provision_email
        domain = os.environ.get("EMAIL_DOMAIN", "softmax-cogents.com")
        region = os.environ.get("AWS_REGION", "us-east-1")
        try:
            from cogtainer.config import load_config
            from cogtainer.runtime.factory import create_runtime
            cogtainer_name = os.environ.get("COGTAINER", "")
            cfg = load_config()
            entry = cfg.cogtainers[cogtainer_name]
            runtime = create_runtime(entry, cogtainer_name)
            result = provision_email(cogent_name, domain=domain, region=region, runtime=runtime)
            click.echo(f"\nEmail provisioned for {cogent_name}:")
            click.echo(f"  Address:      {result['address']}")
            click.echo(f"  Ingest URL:   {result['ingest_url']}")
            click.echo(f"  CF rule ID:   {result.get('cf_rule_id', 'n/a')}")
            click.echo(f"  SES verified: {result.get('ses_verified', False)}")
        except Exception as e:
            click.echo(f"Email provisioning failed: {e}", err=True)
            sys.exit(1)
        return

    click.echo(f"TODO: Implement {io_type} provisioning for {cogent_name}")


@io.command()
@click.argument("io_name")
@click.argument("cogent_name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def destroy(io_name: str, cogent_name: str, yes: bool):
    """Remove an IO integration from a cogent."""
    from cogtainer.secrets import create_secrets_provider

    if not yes:
        click.confirm(f"Delete {io_name} IO integration for {cogent_name}?", abort=True)

    secret_id = f"identity_service/{cogent_name}/{io_name}"

    try:
        provider = create_secrets_provider(provider_type="aws")
        provider.delete_secret(secret_id)
        click.echo(f"Deleted {secret_id}.")
    except Exception as e:
        click.echo(f"Failed to delete {secret_id}: {e}", err=True)
        sys.exit(1)


@io.command()
@click.argument("cogent_name")
def status(cogent_name: str):
    """Show provisioned IO integrations and token status."""
    from cogos.capabilities._secrets_helper import fetch_secret
    from cogtainer.secrets import create_secrets_provider

    prefix = f"identity_service/{cogent_name}/"

    try:
        provider = create_secrets_provider(provider_type="aws")
        secret_keys = provider.list_secrets(prefix)
    except Exception as e:
        click.echo(f"Failed to list IO integrations: {e}", err=True)
        sys.exit(1)

    if not secret_keys:
        click.echo(f"No IO integrations provisioned for '{cogent_name}'.")
        return

    click.echo(f"\nIO integrations for {cogent_name}:\n")
    for key in sorted(secret_keys):
        io_name = key.split("/")[-1]
        try:
            raw = fetch_secret(key, secrets_provider=provider)
            data = json.loads(raw)
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
    if io_name == "email":
        from cogos.io.email.sender import SesSender
        from cogtainer.runtime.factory import create_executor_runtime
        domain = os.environ.get("EMAIL_DOMAIN", "softmax-cogents.com")
        region = os.environ.get("AWS_REGION", "us-east-1")
        from_address = f"{cogent_name}@{domain}"
        runtime = create_executor_runtime()
        sender = SesSender(from_address=from_address, region=region, runtime=runtime)
        try:
            result = sender.send(to=from_address, subject="Test message", body=message)
            click.echo(f"Sent: {result.get('MessageId', 'unknown')}")
        except Exception as e:
            click.echo(f"Send failed: {e}", err=True)
            sys.exit(1)
        return

    click.echo("TODO: Implement send for each IO type")


if __name__ == "__main__":
    io()
