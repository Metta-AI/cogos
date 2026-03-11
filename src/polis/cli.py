"""cogent polis — manage the shared infrastructure hub."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import requests

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
from polis.status import coalesce_status_items, expected_stack_name

console = Console()

# CDK commands need org admin access (OrganizationAccountAccessRole).
# Default profile for CDK operations when --profile is not specified.
CDK_PROFILE = "softmax-org"


@click.group()
@click.option("--profile", default=None, help="AWS profile override (default: use active profile)")
@click.pass_context
def polis(ctx: click.Context, profile: str | None):
    """Manage the polis shared infrastructure."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = PolisConfig()
    ctx.obj["profile"] = profile
    set_profile(profile)


# ---------------------------------------------------------------------------
# Stack management
# ---------------------------------------------------------------------------


@polis.command()
@click.pass_context
def create(ctx: click.Context):
    """Create the polis account and deploy CDK stacks (requires org admin)."""
    config: PolisConfig = ctx.obj["config"]
    profile = ctx.obj["profile"]

    # Org operations need admin — use CDK_PROFILE if no explicit profile
    set_profile(profile or CDK_PROFILE)

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
    _cdk_deploy(org_id, profile=profile or CDK_PROFILE)

    # Cloudflare Access
    polis_session, _ = get_polis_session()
    _ensure_cloudflare_access(polis_session, config.domain)

    console.print("[green]Polis created successfully.[/green]")


@polis.command()
@click.pass_context
def update(ctx: click.Context):
    """Update the polis CDK stacks (requires org admin)."""
    profile = ctx.obj["profile"]

    # Org operations need admin — use CDK_PROFILE if no explicit profile
    set_profile(profile or CDK_PROFILE)

    org_id = get_org_id()
    console.print("Updating CDK stacks...")
    _cdk_deploy(org_id, profile=profile or CDK_PROFILE)

    # Cloudflare Access
    config: PolisConfig = ctx.obj["config"]
    polis_session, _ = get_polis_session()
    _ensure_cloudflare_access(polis_session, config.domain)

    console.print("[green]Polis updated.[/green]")


@polis.command()
@click.pass_context
@click.confirmation_option(prompt="Are you sure you want to destroy the polis stacks?")
def destroy(ctx: click.Context):
    """Tear down the polis CDK stacks (requires org admin)."""
    profile = ctx.obj["profile"]

    # Remove Cloudflare Access Application
    try:
        from polis.cloudflare import delete_access

        polis_session, _ = get_polis_session()
        store = SecretStore(session=polis_session)
        if delete_access(store):
            console.print("  [green]Cloudflare Access Application deleted[/green]")
        else:
            console.print("  Cloudflare Access: not found (skip)")
    except Exception as e:
        console.print(f"  [yellow]Cloudflare Access cleanup: {e}[/yellow]")

    console.print("Destroying CDK stacks...")
    _cdk_cmd(["destroy", "--all", "--force"], profile=profile or CDK_PROFILE)
    console.print("[green]Polis stacks destroyed.[/green]")


_SHORT = {
    "UPDATE_COMPLETE": "ok",
    "CREATE_COMPLETE": "ok",
    "UPDATE_ROLLBACK_COMPLETE": "rollback",
    "CREATE_IN_PROGRESS": "creating",
    "UPDATE_IN_PROGRESS": "updating",
    "DELETE_IN_PROGRESS": "deleting",
    "CREATE_FAILED": "FAILED",
    "UPDATE_FAILED": "FAILED",
    "REGISTERED": "ok",
    "INSUFFICIENT_DATA": "no data",
    "available": "ok",
}


def _status_style(value: str) -> tuple[str, str]:
    """Return (style, short_display) for a status string."""
    v = str(value)
    if v in ("-", "", "None"):
        return "dim", "-"
    short = _SHORT.get(v, v)
    if any(k in v for k in ("COMPLETE", "ACTIVE", "available", "ok", "OK", "REGISTERED")):
        return "green", short
    if any(k in v for k in ("FAILED", "ERROR", "DRAINING", "ALARM", "stale")):
        return "red", short
    if any(k in v for k in ("PROGRESS", "PENDING", "creating", "modifying")):
        return "yellow", short
    if v == "INSUFFICIENT_DATA":
        return "dim", short
    return "cyan", short


@polis.command()
def status():
    """Show polis resource status and per-cogent component health."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    config = PolisConfig()

    try:
        polis_session, _ = get_polis_session()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    # -- Parallel queries (all via polis_session) --------------------------
    results = {}

    def _query_ecr():
        ecr = polis_session.client("ecr")
        repos = ecr.describe_repositories(repositoryNames=["cogent"])["repositories"]
        if not repos:
            return None, []
        uri = repos[0]["repositoryUri"]
        try:
            img_resp = ecr.describe_images(
                repositoryName="cogent",
                filter={"tagStatus": "TAGGED"},
            )
            images = sorted(
                img_resp.get("imageDetails", []),
                key=lambda x: x.get("imagePushedAt", ""),
                reverse=True,
            )
        except Exception:
            images = []
        return uri, images

    def _query_polis_ecs():
        """ECS cluster + dashboard services in polis account."""
        ecs = polis_session.client("ecs")
        cluster = None
        dashboards = {}
        try:
            clusters = ecs.describe_clusters(clusters=["cogent-polis"])["clusters"]
            cluster = clusters[0] if clusters else None
        except Exception:
            pass
        try:
            arns = ecs.list_services(cluster="cogent-polis").get("serviceArns", [])
            if arns:
                desc = ecs.describe_services(cluster="cogent-polis", services=arns)
                for svc in desc.get("services", []):
                    name = svc["serviceName"]
                    if "-DashService" in name or "-dashboard-" in name:
                        sep = "-DashService" if "-DashService" in name else "-dashboard-"
                        cogent = name.split(sep)[0]
                        if cogent.startswith("cogent-"):
                            cogent = cogent[len("cogent-"):]
                        # Strip -brain suffix (e.g. "dr-alpha-brain" -> "dr-alpha")
                        if cogent.endswith("-brain"):
                            cogent = cogent[:-len("-brain")]
                        r = svc.get("runningCount", 0)
                        d = svc.get("desiredCount", 0)
                        dashboards[cogent] = f"ACTIVE {r}/{d}" if svc.get("status") == "ACTIVE" else svc.get("status", "?")
        except Exception:
            pass
        return cluster, dashboards

    def _query_cogents_and_secrets():
        """DynamoDB cogent status + secrets list."""
        ddb = polis_session.resource("dynamodb")
        tbl = ddb.Table("cogent-status")
        items = tbl.scan().get("Items", [])

        sm = polis_session.client("secretsmanager")
        secrets_by_cogent: dict[str, list[str]] = {}
        try:
            paginator = sm.get_paginator("list_secrets")
            for page in paginator.paginate(Filters=[{"Key": "name", "Values": ["cogent/"]}]):
                for s in page["SecretList"]:
                    parts = s["Name"].split("/")
                    if len(parts) >= 3:
                        secrets_by_cogent.setdefault(parts[1], []).append(parts[2])
        except Exception:
            pass
        return items, secrets_by_cogent

    def _query_event_buses():
        """EventBridge buses and rules per cogent."""
        eb = polis_session.client("events")
        buses = {}
        try:
            for bus in eb.list_event_buses(NamePrefix="cogent-")["EventBuses"]:
                name = bus["Name"]
                rules = eb.list_rules(EventBusName=name).get("Rules", [])
                enabled = sum(1 for r in rules if r.get("State") == "ENABLED")
                buses[name] = {"rules": len(rules), "enabled": enabled}
        except Exception:
            pass
        return buses

    all_fns = {
        "ecr": _query_ecr,
        "polis_ecs": _query_polis_ecs,
        "cogents_secrets": _query_cogents_and_secrets,
        "event_buses": _query_event_buses,
    }

    with ThreadPoolExecutor(max_workers=len(all_fns)) as pool:
        futures = {pool.submit(fn): key for key, fn in all_fns.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception:
                results[key] = None

    # -- Polis Resources table -------------------------------------------
    table = Table(title="Polis")
    table.add_column("Resource", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    ecr_uri, ecr_images = results.get("ecr") or (None, [])
    if ecr_uri:
        table.add_row("ECR", "[green]ok[/green]", ecr_uri)
    else:
        table.add_row("ECR", "[red]not found[/red]", "")

    polis_cluster, dashboards = results.get("polis_ecs") or (None, {})
    if polis_cluster:
        running = polis_cluster.get("runningTasksCount", 0)
        table.add_row("ECS Cluster", "[green]ok[/green]", f"cogent-polis  {running} running tasks")
    else:
        table.add_row("ECS Cluster", "[red]not found[/red]", "")

    console.print(table)

    # -- Per-cogent sub-tables (data from watcher via DynamoDB) ----------
    cogent_items, secrets_by_cogent = results.get("cogents_secrets") or ([], {})
    event_buses = results.get("event_buses") or {}

    if not cogent_items:
        console.print("\nNo cogents registered.")
        return

    items = sorted(coalesce_status_items(cogent_items), key=lambda x: x.get("cogent_name", ""))

    for item in items:
        name = item.get("cogent_name", "?")
        safe_name = name.replace(".", "-")
        dashboard_host = item.get("domain") or _cogent_subdomain(name, config.domain)
        dashboard_url = f"https://{dashboard_host}"

        def _cell(val):
            s, d = _status_style(str(val) if val else "-")
            return f"[{s}]{d}[/{s}]"

        # Secrets
        secs = secrets_by_cogent.get(name, [])

        # Channels from watcher
        channels = item.get("channels", {})
        if channels:
            ok = sum(1 for v in channels.values() if v == "ok")
            stale = sum(1 for v in channels.values() if v == "stale")
            if stale:
                ch_str = f"[red]{ok} ok, {stale} stale[/red]"
            else:
                ch_str = f"[green]{ok} ok[/green]"
        else:
            ch_str = "[dim]-[/dim]"

        # Tasks
        running = int(item.get("running_count", 0))
        desired = int(item.get("desired_count", 0))
        tasks_str = f"{running}/{desired}"

        console.print()
        ct = Table(title=f"[bold]{name}[/bold]", show_header=False, padding=(0, 1))
        ct.add_column("Component", style="bold")
        ct.add_column("Status")
        ct.add_row("Stack", _cell(item.get("stack_status")))
        ct.add_row("Tasks", _cell(tasks_str if desired else None))
        ct.add_row("Image", _cell(item.get("image_tag")))
        ct.add_row("CPU (1m/10m)", _cell(f"{int(item.get('cpu_1m', 0))}%/{int(item.get('cpu_10m', 0))}%" if item.get("cpu_1m") else None))
        ct.add_row("Memory", _cell(f"{int(item.get('mem_pct', 0))}%" if item.get("mem_pct") else None))
        ct.add_row("Dashboard", _cell(dashboards.get(safe_name)))
        ct.add_row("Dashboard URL", f"[link={dashboard_url}][underline cyan]{dashboard_url}[/underline cyan][/link]")

        # EventBridge
        bus_name = f"cogent-{safe_name}"
        bus_info = event_buses.get(bus_name)
        if bus_info:
            eb_str = f"[green]{bus_info['enabled']}/{bus_info['rules']} rules enabled[/green]"
        else:
            eb_str = "[dim]-[/dim]"
        ct.add_row("EventBridge", eb_str)

        ct.add_row("Channels", ch_str)
        ct.add_row("Secrets", f"[cyan]{len(secs)}[/cyan]" if secs else "[dim]-[/dim]")
        console.print(ct)

    # -- ECR Images table ------------------------------------------------
    if ecr_images:
        console.print()
        it = Table(title="ECR Images (recent)")
        it.add_column("Tag(s)", style="bold")
        it.add_column("Pushed")
        it.add_column("Size (MB)")
        for img in ecr_images[:10]:
            tags = ", ".join(img.get("imageTags", ["-"]))
            pushed = img.get("imagePushedAt", "")
            pushed_str = pushed.strftime("%Y-%m-%d %H:%M") if hasattr(pushed, "strftime") else str(pushed)
            size_mb = f"{img.get('imageSizeInBytes', 0) / 1024 / 1024:.0f}"
            it.add_row(tags, pushed_str, size_mb)
        console.print(it)


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


def _cogent_subdomain(name: str, domain: str) -> str:
    """Convert cogent name to subdomain (dots become dashes)."""
    return f"{name.replace('.', '-')}.{domain}"


@cogents.command("create")
@click.argument("name")
@click.pass_context
def cogents_create(ctx: click.Context, name: str):
    """Register a cogent's identity in the polis (domain, certificate, secrets)."""
    from polis.cloudflare import ensure_dns_record

    config: PolisConfig = ctx.obj["config"]
    session, _ = get_polis_session()
    store = SecretStore(session=session)

    subdomain = _cogent_subdomain(name, config.domain)
    safe_name = name.replace(".", "-")
    console.print(f"Creating cogent identity: [bold]{name}[/bold]")

    # 1. Cloudflare DNS — placeholder CNAME (will be updated to ALB after stack deploy)
    console.print(f"  Registering domain: [cyan]{subdomain}[/cyan]")
    ensure_dns_record(store, safe_name, "placeholder.invalid", domain=config.domain)
    console.print("  [green]Domain registered (Cloudflare)[/green]")

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

        # Create DNS validation record in Cloudflare
        desc = acm.describe_certificate(CertificateArn=cert_arn)
        for opt in desc["Certificate"].get("DomainValidationOptions", []):
            rr = opt.get("ResourceRecord")
            if rr:
                console.print(f"  Creating validation record: {rr['Name']}")
                _create_cf_validation_record(store, rr, config.domain)
                console.print("  [green]Validation record created (Cloudflare)[/green]")

    # 3. DynamoDB — register in cogent-status table
    console.print("  Registering in status table...")
    ddb = session.resource("dynamodb")
    table_resource = ddb.Table("cogent-status")
    table_resource.put_item(
        Item={
            "cogent_name": name,
            "stack_name": expected_stack_name(name),
            "record_type": "identity",
            "stack_status": "REGISTERED",
            "running_count": 0,
            "desired_count": 0,
            "image_tag": "-",
            "channels": {},
            "domain": subdomain,
            "certificate_arn": cert_arn,
            "cpu_1m": 0,
            "cpu_10m": 0,
            "mem_pct": 0,
            "updated_at": int(time.time()),
        },
    )
    console.print("  [green]Status record created[/green]")

    # 4. Secrets — create identity secret for the cogent
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
    from polis.cloudflare import delete_dns_record

    config: PolisConfig = ctx.obj["config"]
    session, _ = get_polis_session()
    store = SecretStore(session=session)

    subdomain = _cogent_subdomain(name, config.domain)
    safe_name = name.replace(".", "-")
    console.print(f"Destroying cogent identity: [bold]{name}[/bold]")

    # 1. Delete Cloudflare DNS records
    try:
        if delete_dns_record(store, safe_name, domain=config.domain):
            console.print("  [green]Deleted DNS record (Cloudflare)[/green]")
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

    # 3. Delete DynamoDB status record
    try:
        ddb = session.resource("dynamodb")
        table_resource = ddb.Table("cogent-status")
        table_resource.delete_item(Key={"cogent_name": name})
        console.print(f"  [green]Deleted status record[/green]")
    except Exception as e:
        console.print(f"  [yellow]Status cleanup: {e}[/yellow]")

    # 4. Delete all secrets under cogent/{name}/
    store = SecretStore(session=session)
    secrets_list = store.list(f"cogent/{name}/")
    for s in secrets_list:
        store.delete(s)
        console.print(f"  [green]Deleted secret: {s}[/green]")

    console.print(f"\n[green]Cogent {name} removed from polis.[/green]")


@cogents.command("list")
def cogents_list():
    """List all cogents registered in the polis."""
    session, _ = get_polis_session()
    ddb = session.resource("dynamodb")
    table_resource = ddb.Table("cogent-status")

    try:
        resp = table_resource.scan()
    except Exception as e:
        console.print(f"[red]Error reading status table: {e}[/red]")
        return

    items = sorted(coalesce_status_items(resp.get("Items", [])), key=lambda x: x.get("cogent_name", ""))

    if not items:
        console.print("No cogents found.")
        return

    table = Table(title="Cogents")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Domain")
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
        status_style = "green" if "COMPLETE" in stack_status else "cyan" if stack_status == "REGISTERED" else "yellow"

        table.add_row(
            item.get("cogent_name", "?"),
            f"[{status_style}]{stack_status}[/{status_style}]",
            item.get("domain", "-"),
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

    resp = table_resource.scan()
    item = next(
        (
            row
            for row in coalesce_status_items(resp.get("Items", []))
            if row.get("cogent_name") == name or row.get("stack_name") == expected_stack_name(name)
        ),
        None,
    )

    if not item:
        console.print(f"[red]No status found for cogent: {name}[/red]")
        return

    console.print_json(json.dumps(item, default=str))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_cf_validation_record(store: SecretStore, rr: dict, domain: str) -> None:
    """Create a DNS-only CNAME record in Cloudflare for ACM validation."""
    from polis.cloudflare import _load_cf_config, _headers

    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]
    api_token = cf["api_token"]

    # Check if already exists
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(api_token),
        params={"name": rr["Name"].rstrip("."), "type": "CNAME"},
    )
    resp.raise_for_status()
    if resp.json().get("result"):
        return  # already exists

    resp = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(api_token),
        json={
            "type": "CNAME",
            "name": rr["Name"].rstrip("."),
            "content": rr["Value"],
            "proxied": False,  # validation records must not be proxied
        },
    )
    resp.raise_for_status()


def _ensure_cloudflare_access(session, domain: str = "softmax-cogents.com") -> None:
    """Ensure Cloudflare Access Application exists for cogent dashboards."""
    from polis.cloudflare import ensure_access

    store = SecretStore(session=session)
    try:
        app = ensure_access(store, domain=domain)
        console.print(f"  Cloudflare Access: [green]ok[/green] ({app['id']})")
    except Exception as e:
        console.print(f"  [yellow]Cloudflare Access: {e}[/yellow]")


def _cdk_deploy(org_id: str, profile: str | None = None):
    """Run cdk deploy with the org_id context."""
    _cdk_cmd(
        ["deploy", "--all", "--require-approval", "never", "-c", f"org_id={org_id}"],
        profile=profile,
    )


def _cdk_cmd(args: list[str], profile: str | None = None):
    """Run a CDK CLI command. Uses CDK_PROFILE for org-level access."""
    cmd = ["npx", "cdk", *args, "--app", "python -m polis.cdk.app"]
    env = {**os.environ, "AWS_PROFILE": profile or CDK_PROFILE}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        console.print(f"[red]CDK command failed (exit {result.returncode})[/red]")
        sys.exit(result.returncode)
