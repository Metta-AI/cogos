"""cogent polis — manage the shared infrastructure hub."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import click
from rich.console import Console
from rich.table import Table

from polis.aws import (
    create_polis_account,
    find_polis_account,
    get_org_id,
    get_polis_session,
    set_profile,
)
from polis.config import PolisConfig
from polis.secrets.store import SecretStore

console = Console()


@click.group()
@click.option("--profile", default="softmax-org", help="AWS profile for org operations")
@click.pass_context
def polis(ctx: click.Context, profile: str):
    """Manage the polis shared infrastructure."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = PolisConfig()
    set_profile(profile)


# ---------------------------------------------------------------------------
# Stack management
# ---------------------------------------------------------------------------


@polis.command()
@click.pass_context
def create(ctx: click.Context):
    """Create the polis account and deploy CDK stacks."""
    config: PolisConfig = ctx.obj["config"]

    console.print(f"Creating polis: [bold]{config.name}[/bold]")

    # Find or create polis account
    account_id = find_polis_account()
    if account_id:
        console.print(f"  Polis account already exists: {account_id}")
    else:
        console.print("  Creating polis account...")
        account_id = create_polis_account()
        console.print(f"  Created account: {account_id}")

    org_id = get_org_id()

    # Deploy CDK
    console.print("  Deploying CDK stacks...")
    _cdk_deploy(org_id)
    console.print("[green]Polis created successfully.[/green]")


@polis.command()
@click.pass_context
def update(ctx: click.Context):
    """Update the polis CDK stacks."""
    org_id = get_org_id()
    console.print("Updating CDK stacks...")
    _cdk_deploy(org_id)
    console.print("[green]Polis updated.[/green]")


@polis.command()
@click.confirmation_option(prompt="Are you sure you want to destroy the polis stacks?")
def destroy():
    """Tear down the polis CDK stacks."""
    console.print("Destroying CDK stacks...")
    _cdk_cmd(["destroy", "--all", "--force"])
    console.print("[green]Polis stacks destroyed.[/green]")


@polis.command()
def status():
    """Show polis resource status."""
    account_id = find_polis_account()
    if not account_id:
        console.print("[red]No polis account found.[/red]")
        return

    session, _ = get_polis_session()

    table = Table(title="Polis Resources")
    table.add_column("Resource", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    # ECR
    try:
        ecr = session.client("ecr")
        repos = ecr.describe_repositories(repositoryNames=["cogent"])["repositories"]
        if repos:
            uri = repos[0]["repositoryUri"]
            table.add_row("ECR", "[green]active[/green]", uri)
    except Exception:
        table.add_row("ECR", "[red]not found[/red]", "")

    # ECS Cluster
    try:
        ecs = session.client("ecs")
        clusters = ecs.describe_clusters(clusters=["cogent-polis"])["clusters"]
        if clusters:
            c = clusters[0]
            count = c.get("registeredContainerInstancesCount", 0)
            running = c.get("runningTasksCount", 0)
            table.add_row("ECS Cluster", "[green]active[/green]", f"{running} running tasks")
    except Exception:
        table.add_row("ECS Cluster", "[red]not found[/red]", "")

    # DynamoDB
    try:
        ddb = session.client("dynamodb")
        t = ddb.describe_table(TableName="cogent-status")["Table"]
        item_count = t.get("ItemCount", 0)
        table.add_row("DynamoDB", "[green]active[/green]", f"{item_count} items")
    except Exception:
        table.add_row("DynamoDB", "[red]not found[/red]", "")

    console.print(table)


# ---------------------------------------------------------------------------
# Secrets management
# ---------------------------------------------------------------------------


@polis.group()
def secrets():
    """Manage cogent secrets."""


@secrets.command("list")
@click.option("--cogent", default=None, help="Filter by cogent name")
def secrets_list(cogent: str | None):
    """List secrets."""
    session, _ = get_polis_session()
    store = SecretStore(session=session)

    prefix = f"cogent/{cogent}/" if cogent else "cogent/"
    names = store.list(prefix)

    if not names:
        console.print("No secrets found.")
        return

    table = Table(title="Secrets")
    table.add_column("Path", style="bold")
    for name in names:
        table.add_row(name)
    console.print(table)


@secrets.command("get")
@click.argument("path")
def secrets_get(path: str):
    """Get a secret value."""
    session, _ = get_polis_session()
    store = SecretStore(session=session)
    value = store.get(path)
    # Redact access_token if present
    display = {**value}
    if "access_token" in display:
        tok = display["access_token"]
        display["access_token"] = tok[:8] + "..." if len(tok) > 8 else "***"
    console.print_json(json.dumps(display))


@secrets.command("set")
@click.argument("path")
@click.option("--value", default=None, help="JSON string value")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="JSON file")
def secrets_set(path: str, value: str | None, file_path: str | None):
    """Create or update a secret."""
    if file_path:
        with open(file_path) as f:
            data = json.load(f)
    elif value:
        data = json.loads(value)
    else:
        console.print("[red]Provide --value or --file[/red]")
        return

    session, _ = get_polis_session()
    store = SecretStore(session=session)
    store.put(path, data)
    console.print(f"[green]Secret stored: {path}[/green]")


@secrets.command("delete")
@click.argument("path")
@click.confirmation_option(prompt="Are you sure?")
def secrets_delete(path: str):
    """Delete a secret."""
    session, _ = get_polis_session()
    store = SecretStore(session=session)
    store.delete(path)
    console.print(f"[green]Secret deleted: {path}[/green]")


@secrets.command("rotate")
@click.argument("path")
def secrets_rotate(path: str):
    """Trigger rotation for a secret."""
    session, _ = get_polis_session()
    sm = session.client("secretsmanager")
    sm.rotate_secret(SecretId=path)
    console.print(f"[green]Rotation triggered: {path}[/green]")


# ---------------------------------------------------------------------------
# Cogents listing
# ---------------------------------------------------------------------------


@polis.group()
def cogents():
    """Manage cogents in the polis."""


HOSTED_ZONE_ID = "Z059653727QDSCT3DI6DS"


def _cogent_subdomain(name: str, domain: str) -> str:
    """Convert cogent name to subdomain (dots become dashes)."""
    return f"{name.replace('.', '-')}.{domain}"


@cogents.command("create")
@click.argument("name")
@click.pass_context
def cogents_create(ctx: click.Context, name: str):
    """Register a cogent's identity in the polis (domain, certificate, secrets)."""
    config: PolisConfig = ctx.obj["config"]
    session, _ = get_polis_session()

    subdomain = _cogent_subdomain(name, config.domain)
    console.print(f"Creating cogent identity: [bold]{name}[/bold]")

    # 1. Route53 — placeholder A record for the subdomain
    console.print(f"  Registering domain: [cyan]{subdomain}[/cyan]")
    r53 = session.client("route53")
    r53.change_resource_record_sets(
        HostedZoneId=HOSTED_ZONE_ID,
        ChangeBatch={
            "Comment": f"Register cogent {name}",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": subdomain,
                        "Type": "A",
                        "TTL": 300,
                        "ResourceRecords": [{"Value": "127.0.0.1"}],
                    },
                }
            ],
        },
    )
    console.print("  [green]Domain registered[/green]")

    # 2. ACM — request certificate with DNS validation
    console.print(f"  Requesting ACM certificate for [cyan]{subdomain}[/cyan]")
    acm = session.client("acm")

    # Check for existing certificate first
    cert_arn = None
    paginator = acm.get_paginator("list_certificates")
    for page in paginator.paginate(CertificateStatuses=["PENDING_VALIDATION", "ISSUED"]):
        for cert in page["CertificateSummaryList"]:
            if cert["DomainName"] == subdomain:
                cert_arn = cert["CertificateArn"]
                console.print(f"  Certificate already exists: {cert_arn}")
                break
        if cert_arn:
            break

    if not cert_arn:
        resp = acm.request_certificate(
            DomainName=subdomain,
            ValidationMethod="DNS",
            Tags=[
                {"Key": "cogent", "Value": name},
                {"Key": "managed-by", "Value": "polis"},
            ],
        )
        cert_arn = resp["CertificateArn"]
        console.print(f"  Certificate requested: {cert_arn}")

        # Wait for DNS validation records to appear
        console.print("  Waiting for validation records...")
        for _ in range(30):
            desc = acm.describe_certificate(CertificateArn=cert_arn)
            options = desc["Certificate"].get("DomainValidationOptions", [])
            if options and "ResourceRecord" in options[0]:
                break
            time.sleep(2)
        else:
            console.print("[yellow]  Timed out waiting for validation records[/yellow]")

        # Create DNS validation record in Route53
        desc = acm.describe_certificate(CertificateArn=cert_arn)
        for opt in desc["Certificate"].get("DomainValidationOptions", []):
            rr = opt.get("ResourceRecord")
            if rr:
                console.print(f"  Creating validation record: {rr['Name']}")
                r53.change_resource_record_sets(
                    HostedZoneId=HOSTED_ZONE_ID,
                    ChangeBatch={
                        "Comment": f"ACM validation for {subdomain}",
                        "Changes": [
                            {
                                "Action": "UPSERT",
                                "ResourceRecordSet": {
                                    "Name": rr["Name"],
                                    "Type": rr["Type"],
                                    "TTL": 300,
                                    "ResourceRecords": [{"Value": rr["Value"]}],
                                },
                            }
                        ],
                    },
                )
                console.print("  [green]Validation record created[/green]")

    # 3. Secrets — create identity secret for the cogent
    console.print("  Creating identity secret...")
    store = SecretStore(session=session)
    identity_path = f"cogent/{name}/identity"
    try:
        store.get(identity_path, use_cache=False)
        console.print(f"  Secret already exists: {identity_path}")
    except Exception:
        store.put(
            identity_path,
            {
                "cogent_name": name,
                "domain": subdomain,
                "certificate_arn": cert_arn,
                "created_by": "polis",
            },
        )
        console.print(f"  [green]Secret created: {identity_path}[/green]")

    # Summary
    console.print()
    table = Table(title=f"Cogent Identity: {name}")
    table.add_column("Resource", style="bold")
    table.add_column("Value")
    table.add_row("Domain", subdomain)
    table.add_row("Certificate", cert_arn)
    table.add_row("Identity Secret", identity_path)
    console.print(table)
    console.print(f"\n[green]Cogent {name} registered in polis.[/green]")


@cogents.command("destroy")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to destroy this cogent's identity?")
@click.pass_context
def cogents_destroy(ctx: click.Context, name: str):
    """Remove a cogent's identity from the polis (domain, certificate, secrets)."""
    config: PolisConfig = ctx.obj["config"]
    session, _ = get_polis_session()

    subdomain = _cogent_subdomain(name, config.domain)
    console.print(f"Destroying cogent identity: [bold]{name}[/bold]")

    # 1. Delete Route53 records
    r53 = session.client("route53")
    try:
        resp = r53.list_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            StartRecordName=subdomain,
            MaxItems="10",
        )
        changes = []
        for rrs in resp["ResourceRecordSets"]:
            if rrs["Name"].rstrip(".") == subdomain or rrs["Name"].rstrip(".").startswith(
                f"_"
            ):
                # Only delete A records for the subdomain and CNAME validation records
                if rrs["Type"] in ("A", "CNAME") and subdomain in rrs["Name"]:
                    changes.append({"Action": "DELETE", "ResourceRecordSet": rrs})

        if changes:
            r53.change_resource_record_sets(
                HostedZoneId=HOSTED_ZONE_ID,
                ChangeBatch={"Comment": f"Remove cogent {name}", "Changes": changes},
            )
            console.print(f"  [green]Deleted {len(changes)} DNS record(s)[/green]")
        else:
            console.print("  No DNS records found")
    except Exception as e:
        console.print(f"  [yellow]DNS cleanup: {e}[/yellow]")

    # 2. Delete ACM certificate
    acm = session.client("acm")
    try:
        paginator = acm.get_paginator("list_certificates")
        for page in paginator.paginate():
            for cert in page["CertificateSummaryList"]:
                if cert["DomainName"] == subdomain:
                    acm.delete_certificate(CertificateArn=cert["CertificateArn"])
                    console.print(f"  [green]Deleted certificate: {cert['CertificateArn']}[/green]")
    except Exception as e:
        console.print(f"  [yellow]Certificate cleanup: {e}[/yellow]")

    # 3. Delete all secrets under cogent/{name}/
    store = SecretStore(session=session)
    secrets_list = store.list(f"cogent/{name}/")
    for s in secrets_list:
        store.delete(s)
        console.print(f"  [green]Deleted secret: {s}[/green]")

    console.print(f"\n[green]Cogent {name} removed from polis.[/green]")


@cogents.command("list")
def cogents_list():
    """List all cogents with status from DynamoDB."""
    session, _ = get_polis_session()
    ddb = session.resource("dynamodb")
    table_resource = ddb.Table("cogent-status")

    try:
        resp = table_resource.scan()
    except Exception as e:
        console.print(f"[red]Error reading status table: {e}[/red]")
        return

    items = sorted(resp.get("Items", []), key=lambda x: x.get("cogent_name", ""))

    if not items:
        console.print("No cogents found.")
        return

    table = Table(title="Cogents")
    table.add_column("Name", style="bold")
    table.add_column("Stack Status")
    table.add_column("Tasks")
    table.add_column("Image")
    table.add_column("CPU (1m)")
    table.add_column("Mem %")
    table.add_column("Channels")

    for item in items:
        running = item.get("running_count", 0)
        desired = item.get("desired_count", 0)
        tasks = f"{running}/{desired}"

        channels = item.get("channels", {})
        ch_str = ", ".join(f"{k}:{v}" for k, v in sorted(channels.items())) if channels else "-"

        stack_status = item.get("stack_status", "?")
        status_style = "green" if "COMPLETE" in stack_status else "yellow"

        table.add_row(
            item.get("cogent_name", "?"),
            f"[{status_style}]{stack_status}[/{status_style}]",
            tasks,
            str(item.get("image_tag", "-")),
            str(item.get("cpu_1m", "-")),
            str(item.get("mem_pct", "-")),
            ch_str,
        )

    console.print(table)


@cogents.command("status")
@click.argument("name")
def cogents_status(name: str):
    """Show detailed status for a cogent."""
    session, _ = get_polis_session()
    ddb = session.resource("dynamodb")
    table_resource = ddb.Table("cogent-status")

    resp = table_resource.get_item(Key={"cogent_name": name})
    item = resp.get("Item")

    if not item:
        console.print(f"[red]No status found for cogent: {name}[/red]")
        return

    console.print_json(json.dumps(item, default=str))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cdk_deploy(org_id: str):
    """Run cdk deploy with the org_id context."""
    _cdk_cmd(["deploy", "--all", "--require-approval", "never", "-c", f"org_id={org_id}"])


def _cdk_cmd(args: list[str]):
    """Run a CDK CLI command."""
    cmd = ["npx", "cdk", *args, "--app", "python -m polis.cdk.app"]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        console.print(f"[red]CDK command failed (exit {result.returncode})[/red]")
        sys.exit(result.returncode)
