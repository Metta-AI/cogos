"""cogent cogtainer — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click

from cli import DefaultCommandGroup, get_cogent_name  # noqa: F401
from polis import naming
from polis.aws import DEFAULT_ORG_PROFILE, ORG_PROFILE_ENV

_PROFILE_HELP = (
    f"AWS profile for polis account (default: ${ORG_PROFILE_ENV} or {DEFAULT_ORG_PROFILE})"
)


@click.group(cls=DefaultCommandGroup, default_cmd="status")
def cogtainer():
    """Manage cogent infrastructure, ECS, and Lambda components."""
    pass


@cogtainer.command("status")
@click.pass_context
def status_cmd(ctx: click.Context):
    """Show infrastructure status for a cogent."""
    from rich.console import Console
    from rich.table import Table

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    stack_name = f"cogent-{safe_name}-cogtainer"
    console = Console()

    table = Table(title=f"Cogtainer Status: {name}")
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    from polis.aws import get_polis_session, set_org_profile

    set_org_profile()
    try:
        session, _ = get_polis_session()
    except Exception as e:
        table.add_row("Polis", "[red]cannot connect[/red]", str(e)[:60])
        console.print(table)
        return

    cf = session.client("cloudformation")

    # CloudFormation stack
    try:
        resp = cf.describe_stacks(StackName=stack_name)
        stack = resp["Stacks"][0]
        stack_status = stack["StackStatus"]
        style = "green" if "COMPLETE" in stack_status else "yellow"
        table.add_row("Stack", f"[{style}]{stack_status}[/{style}]", stack_name)
    except Exception:
        table.add_row("Stack", "[red]not found[/red]", stack_name)
        console.print(table)
        return

    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

    # Lambda functions
    lam = session.client("lambda")
    for suffix in ("orchestrator", "executor", "dispatcher"):
        fn_name = f"cogent-{safe_name}-{suffix}"
        try:
            fn = lam.get_function(FunctionName=fn_name)
            cfg = fn["Configuration"]
            state = cfg.get("State", "?")
            last_mod = cfg.get("LastModified", "?")
            mem = cfg.get("MemorySize", "?")
            timeout = cfg.get("Timeout", "?")
            runtime = cfg.get("Runtime", "?")
            style = "green" if state == "Active" else "yellow"
            table.add_row(
                f"Lambda ({suffix})",
                f"[{style}]{state}[/{style}]",
                f"{runtime} {mem}MB {timeout}s | modified {last_mod}",
            )
        except Exception as e:
            err = str(e)
            if "ResourceNotFoundException" in type(e).__name__ or "not found" in err.lower():
                table.add_row(f"Lambda ({suffix})", "[dim]not found[/dim]", fn_name)
            else:
                table.add_row(f"Lambda ({suffix})", "[red]error[/red]", err[:60])

    # Aurora Serverless (shared cluster from polis stack)
    try:
        polis_resp = cf.describe_stacks(StackName="cogent-polis")
        polis_outputs = {o["OutputKey"]: o["OutputValue"] for o in polis_resp["Stacks"][0].get("Outputs", [])}
        cluster_arn = polis_outputs.get("SharedDbClusterArn", "")
    except Exception:
        cluster_arn = ""
    if cluster_arn:
        try:
            cluster_id = cluster_arn.split(":")[-1]
            rds = session.client("rds")
            db_clusters = rds.describe_db_clusters(DBClusterIdentifier=cluster_id)["DBClusters"]
            if db_clusters:
                c = db_clusters[0]
                db_status = c.get("Status", "?")
                style = "green" if db_status == "available" else "yellow"
                capacity = c.get("ServerlessV2ScalingConfiguration", {})
                cap_str = f"min={capacity.get('MinCapacity', '?')} max={capacity.get('MaxCapacity', '?')}" if capacity else ""
                db_name = f"cogent_{safe_name.replace('-', '_')}"
                table.add_row("Aurora", f"[{style}]{db_status}[/{style}]", f"db={db_name} {cap_str}")
        except Exception as e:
            table.add_row("Aurora", "[red]error[/red]", str(e)[:60])
    else:
        table.add_row("Aurora", "[dim]no output[/dim]", "SharedDbClusterArn not in polis stack outputs")

    # ECR — latest image for this cogent
    try:
        ecr = session.client("ecr")
        images = ecr.describe_images(
            repositoryName=naming.ecr_repo_name(),
            filter={"tagStatus": "TAGGED"},
        ).get("imageDetails", [])
        # Find images tagged with this cogent's name
        cogent_images = [
            img for img in images
            if any(safe_name in (t or "") for t in img.get("imageTags", []))
        ]
        if cogent_images:
            latest = max(cogent_images, key=lambda i: i.get("imagePushedAt", ""))
            tags = ", ".join(latest.get("imageTags", [])[:3])
            pushed = str(latest.get("imagePushedAt", "?"))
            size_mb = latest.get("imageSizeInBytes", 0) / 1024 / 1024
            table.add_row("ECR Image", "[green]found[/green]", f"{tags} ({size_mb:.0f}MB) pushed {pushed}")
        elif images:
            # Show latest image regardless of tag
            latest = max(images, key=lambda i: i.get("imagePushedAt", ""))
            tags = ", ".join(latest.get("imageTags", [])[:3])
            pushed = str(latest.get("imagePushedAt", "?"))
            table.add_row("ECR Image", "[yellow]no cogent tag[/yellow]", f"latest: {tags} pushed {pushed}")
        else:
            table.add_row("ECR Image", "[dim]no images[/dim]", "")
    except Exception as e:
        table.add_row("ECR Image", "[red]error[/red]", str(e)[:60])

    # Dashboard (ALB + ECS service on shared cogent-polis cluster)
    alb_dns = outputs.get("AlbDns", "")
    dashboard_url = outputs.get("DashboardUrl", "")
    if alb_dns:
        try:
            elbv2 = session.client("elbv2")
            lbs = elbv2.describe_load_balancers()["LoadBalancers"]
            alb = next((lb for lb in lbs if lb["DNSName"] == alb_dns), None)
            if alb:
                alb_state = alb.get("State", {}).get("Code", "?")
                style = "green" if alb_state == "active" else "yellow"
                table.add_row("Dashboard ALB", f"[{style}]{alb_state}[/{style}]", dashboard_url or alb_dns)
            else:
                table.add_row("Dashboard ALB", "[yellow]not found[/yellow]", alb_dns)
        except Exception as e:
            table.add_row("Dashboard ALB", "[red]error[/red]", str(e)[:60])
    else:
        table.add_row("Dashboard ALB", "[dim]no output[/dim]", "no certificate configured")

    # ECS — shared cogent-polis cluster, look for dashboard service
    ecs_client = session.client("ecs")
    try:
        services = ecs_client.list_services(cluster="cogent-polis").get("serviceArns", [])
        cogent_services = [s for s in services if safe_name in s]
        if cogent_services:
            svc_desc = ecs_client.describe_services(cluster="cogent-polis", services=cogent_services)["services"]
            for svc in svc_desc:
                svc_name = svc["serviceName"]
                svc_status = svc.get("status", "?")
                desired = svc.get("desiredCount", 0)
                running_svc = svc.get("runningCount", 0)
                style = "green" if running_svc >= desired and running_svc > 0 else "yellow" if running_svc > 0 else "red"
                table.add_row("Dashboard ECS", f"[{style}]{svc_status}[/{style}]", f"{svc_name} ({running_svc}/{desired})")
        else:
            table.add_row("Dashboard ECS", "[dim]no service[/dim]", "")
    except Exception:
        pass  # ECS query may fail if cluster doesn't exist

    console.print(table)


@cogtainer.command("cleanup")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--keep", default=5, type=int, help="Number of old ECS task definition revisions to keep")
@click.option("--dry-run", is_flag=True, help="Show what would be cleaned up without doing it")
@click.pass_context
def cleanup_cmd(ctx: click.Context, profile: str | None, keep: int, dry_run: bool):
    """Clean up old ECS task definitions and stale Lambda functions."""
    from polis.aws import get_polis_session, resolve_org_profile, set_org_profile

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    profile = resolve_org_profile(profile)
    set_org_profile(profile)
    session, _ = get_polis_session()

    click.echo(f"Cleaning up old resources for cogent-{name}...")

    _cleanup_task_definitions(session, safe_name, keep, dry_run)
    _cleanup_stale_lambdas(session, safe_name, dry_run)

    click.echo("\nCleanup complete.")


def _cleanup_task_definitions(
    session: object, safe_name: str, keep: int, dry_run: bool
) -> None:
    from polis.aws import DEFAULT_REGION

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)  # type: ignore[union-attr]
    prefix = f"{naming.RESOURCE_PREFIX}-{safe_name}-"

    click.echo(f"\nECS task definitions (prefix={prefix}, keep={keep}):")

    families: list[str] = []
    paginator = ecs_client.get_paginator("list_task_definition_families")
    for page in paginator.paginate(familyPrefix=prefix, status="ACTIVE"):
        families.extend(page["families"])

    if not families:
        click.echo("  No task definition families found.")
        return

    total_deregistered = 0
    for family in families:
        arns: list[str] = []
        td_paginator = ecs_client.get_paginator("list_task_definitions")
        for page in td_paginator.paginate(familyPrefix=family, sort="DESC", status="ACTIVE"):
            arns.extend(page["taskDefinitionArns"])

        if len(arns) <= keep:
            click.echo(f"  {family}: {len(arns)} revision(s), nothing to clean")
            continue

        to_deregister = arns[keep:]
        if dry_run:
            click.echo(f"  {family}: would deregister {len(to_deregister)} old revision(s)")
            continue

        deregistered = 0
        for arn in to_deregister:
            try:
                ecs_client.deregister_task_definition(taskDefinition=arn)
                deregistered += 1
            except Exception:
                pass
        total_deregistered += deregistered
        click.echo(
            f"  {family}: deregistered {deregistered}/{len(to_deregister)} old revision(s) "
            f"(kept {keep})"
        )

    if dry_run:
        click.echo("  (dry run, no changes made)")
    elif total_deregistered:
        click.echo(f"  Total deregistered: {total_deregistered}")


def _cleanup_stale_lambdas(session: object, safe_name: str, dry_run: bool) -> None:
    from polis.aws import DEFAULT_REGION

    lambda_client = session.client("lambda", region_name=DEFAULT_REGION)  # type: ignore[union-attr]
    prefix = f"{naming.RESOURCE_PREFIX}-{safe_name}-"

    active_fns = {
        naming.lambda_name(safe_name, suffix)
        for suffix in ("orchestrator", "executor", "dispatcher", "ingress", "sandbox")
    }

    click.echo(f"\nLambda functions (prefix={prefix}):")

    stale: list[str] = []
    paginator = lambda_client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            fn_name = fn["FunctionName"]
            if fn_name.startswith(prefix) and fn_name not in active_fns:
                stale.append(fn_name)

    if not stale:
        click.echo("  No stale Lambda functions found.")
        return

    for fn_name in stale:
        if dry_run:
            click.echo(f"  Would delete: {fn_name}")
        else:
            try:
                lambda_client.delete_function(FunctionName=fn_name)
                click.echo(f"  Deleted: {fn_name}")
            except Exception as e:
                click.echo(f"  Failed to delete {fn_name}: {e}")

    if dry_run:
        click.echo("  (dry run, no changes made)")


@cogtainer.command("await")
@click.option("--prefix", default="executor", help="Image tag prefix (executor or dashboard)")
@click.option("--tag", default=None, help="Exact ECR tag to wait for (overrides --prefix + commit SHA)")
@click.option("--timeout", default=300, help="Max seconds to wait")
@click.option("--profile", default=None, help=_PROFILE_HELP)
def await_cmd(prefix: str, tag: str | None, timeout: int, profile: str | None):
    """Wait for a CI-built ECR image to be available.

    \b
    By default waits for an image matching the current git commit:
      cogent <name> cogtainer await                         # executor-<sha>
      cogent <name> cogtainer await --prefix dashboard      # dashboard-<sha>

    Or wait for a specific tag:
      cogent <name> cogtainer await --tag executor-latest
    """
    import subprocess
    import time

    from polis.aws import get_polis_session, set_org_profile

    if tag:
        expected_tag = tag
    else:
        sha_short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        expected_tag = f"{prefix}-{sha_short}"

    click.echo(f"Waiting for ECR tag '{expected_tag}'...")

    set_org_profile(profile)
    session, _ = get_polis_session()
    ecr_client = session.client("ecr", region_name="us-east-1")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = ecr_client.describe_images(
                repositoryName=naming.ecr_repo_name(),
                imageIds=[{"imageTag": expected_tag}],
            )
            pushed = resp["imageDetails"][0].get("imagePushedAt", "")
            click.echo(click.style(f"  Image found: cogent:{expected_tag} (pushed {pushed})", fg="green"))
            return
        except Exception:
            remaining = int(deadline - time.monotonic())
            click.echo(f"  Not yet ({remaining}s remaining)...", nl=True)
            time.sleep(10)

    raise click.ClickException(
        f"Timed out waiting for ECR tag '{expected_tag}' after {timeout}s.\n"
        f"Check CI: gh run list --repo Metta-AI/cogos --workflow docker-build-{prefix}.yml"
    )


# Wire in update subcommands
from cogtainer.update_cli import update  # noqa: E402

cogtainer.add_command(update)
