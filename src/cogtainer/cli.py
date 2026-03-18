"""cogent cogtainer — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click

from cli import DefaultCommandGroup, get_cogent_name  # noqa: F401
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

    # Aurora Serverless
    cluster_arn = outputs.get("ClusterArn", "")
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
                table.add_row("Aurora", f"[{style}]{db_status}[/{style}]", cap_str)
        except Exception as e:
            table.add_row("Aurora", "[red]error[/red]", str(e)[:60])
    else:
        table.add_row("Aurora", "[dim]no output[/dim]", "ClusterArn not in stack outputs")

    # ECR — latest image for this cogent
    try:
        ecr = session.client("ecr")
        images = ecr.describe_images(
            repositoryName="cogent",
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


@cogtainer.command("create")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.pass_context
def create_cmd(ctx: click.Context, profile: str | None):
    """Deploy a cogent's cogtainer infrastructure in the polis account."""
    import os
    import subprocess
    import time

    from cogtainer.update_cli import (
        _build_dashboard_tarball,
        _ensure_discord_bridge_state,
        _get_polis_admin_session,
        _sessions_bucket_name,
        _upload_dashboard_tarball,
        _wait_for_bucket,
    )
    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")

    # Look up certificate ARN and ECR repo URI from polis account
    from polis.aws import get_polis_session, resolve_org_profile, set_profile

    profile = resolve_org_profile(profile)
    set_profile(profile)
    polis_session, _ = get_polis_session()
    cert_arn = _find_certificate(polis_session, f"{safe_name}.softmax-cogents.com")

    ecr_repo_uri = ""
    try:
        ecr_client = polis_session.client("ecr")
        repos = ecr_client.describe_repositories(repositoryNames=["cogent"])["repositories"]
        ecr_repo_uri = repos[0]["repositoryUri"]
    except Exception:
        click.echo("Warning: Could not resolve polis ECR repo. Using default image.")

    click.echo(f"Deploying cogtainer for cogent-{name} in polis account...")
    if cert_arn:
        click.echo(f"  Certificate: {cert_arn}")

    click.echo("Preparing dashboard bootstrap assets...")
    tarball_path, _size_mb = _build_dashboard_tarball()
    bootstrap_bucket = _sessions_bucket_name(safe_name)
    admin_session = _get_polis_admin_session(profile)

    cmd = [
        "npx", "cdk", "deploy", f"cogent-{safe_name}-cogtainer",
        "-c", f"cogent_name={name}",
        "-c", f"certificate_arn={cert_arn}",
        "-c", f"ecr_repo_uri={ecr_repo_uri}",
        "--app", "python -m cogtainer.cdk.app",
        "--require-approval", "never",
    ]
    env = {**os.environ, "AWS_PROFILE": profile}
    deploy = subprocess.Popen(cmd, env=env)
    uploaded_assets = False
    deadline = time.monotonic() + 600
    try:
        while deploy.poll() is None and not uploaded_assets and time.monotonic() < deadline:
            if _wait_for_bucket(admin_session, bootstrap_bucket, timeout_s=5, poll_s=5):
                click.echo("Uploading dashboard bootstrap assets...")
                try:
                    s3_uri = _upload_dashboard_tarball(admin_session, bootstrap_bucket, tarball_path)
                except Exception as e:
                    deploy.terminate()
                    try:
                        deploy.wait(timeout=10)
                    except Exception:
                        pass
                    raise click.ClickException(f"Dashboard bootstrap upload failed: {e}") from e
                click.echo(f"  Upload: {s3_uri}")
                uploaded_assets = True

        result_code = deploy.wait()
        if result_code == 0 and not uploaded_assets:
            click.echo("Uploading dashboard bootstrap assets...")
            s3_uri = _upload_dashboard_tarball(admin_session, bootstrap_bucket, tarball_path)
            click.echo(f"  Upload: {s3_uri}")
            uploaded_assets = True
        elif not uploaded_assets:
            click.echo(
                f"Warning: sessions bucket {bootstrap_bucket} did not appear before timeout; "
                "dashboard may still need a manual deploy.",
                err=True,
            )
    finally:
        if os.path.exists(tarball_path):
            os.unlink(tarball_path)

    if result_code != 0:
        raise click.ClickException("CDK deploy failed")
    click.echo(f"Cogtainer infrastructure for cogent-{name} deployed in polis account.")

    # Re-assume role with full admin to read stack outputs (cogent-polis-admin lacks CF perms)
    try:
        admin_session = _get_polis_admin_session(profile)
        admin_creds = admin_session.get_credentials().get_frozen_credentials()
        cf = admin_session.client("cloudformation", region_name="us-east-1")
        resp = cf.describe_stacks(StackName=f"cogent-{safe_name}-cogtainer")
        outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
        if "ClusterArn" in outputs:
            os.environ["DB_CLUSTER_ARN"] = outputs["ClusterArn"]
        if "SecretArn" in outputs:
            os.environ["DB_SECRET_ARN"] = outputs["SecretArn"]
        else:
            resources = cf.list_stack_resources(StackName=f"cogent-{safe_name}-cogtainer")
            for r in resources.get("StackResourceSummaries", []):
                if "Secret" in r["LogicalResourceId"] and "Attachment" not in r["LogicalResourceId"]:
                    if r["PhysicalResourceId"].startswith("arn:aws:secretsmanager:"):
                        os.environ["DB_SECRET_ARN"] = r["PhysicalResourceId"]
                        break
        # Set AWS credentials so apply_schema() can access RDS Data API in polis account
        os.environ["AWS_ACCESS_KEY_ID"] = admin_creds.access_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = admin_creds.secret_key
        if admin_creds.token:
            os.environ["AWS_SESSION_TOKEN"] = admin_creds.token
    except Exception as e:
        click.echo(f"Warning: could not read stack outputs: {e}")

    # Apply database schema
    click.echo("Applying database schema...")
    from cogos.db.migrations import apply_schema
    schema_ready = False
    try:
        apply_schema()
        schema_ready = True
        click.echo("Database schema applied.")
    except Exception as e:
        click.echo(f"Warning: schema apply failed: {e}")

    if schema_ready:
        try:
            discord_action = _ensure_discord_bridge_state(
                polis_session,
                name,
                safe_name,
                previous_desired_count=None,
            )
        except Exception as e:
            click.echo(f"Warning: could not reconcile Discord bridge state: {e}")
        else:
            if discord_action == ("autostarted", 1):
                click.echo(f"Starting Discord bridge for cogent-{name} because a token is configured...")

    # Update Cloudflare DNS to point at the dashboard ALB
    if cert_arn:
        click.echo("Updating DNS...")
        try:
            from polis.cloudflare import ensure_dns_record
            from polis.secrets.store import SecretStore

            dns_session = _get_polis_admin_session(profile)
            store = SecretStore(session=dns_session)
            cfn = dns_session.client("cloudformation", region_name="us-east-1")
            resp = cfn.describe_stacks(StackName=f"cogent-{safe_name}-cogtainer")
            outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
            alb_dns = outputs.get("AlbDns", "")
            if alb_dns:
                ensure_dns_record(store, safe_name, alb_dns)
                click.echo(f"  DNS updated: {safe_name}.softmax-cogents.com -> {alb_dns}")
            else:
                click.echo("  No AlbDns output found, skipping DNS update")
        except Exception as e:
            click.echo(f"Warning: DNS update failed: {e}")


def _find_certificate(session, domain: str) -> str:
    """Find an ACM certificate ARN for the given domain."""
    acm = session.client("acm")
    paginator = acm.get_paginator("list_certificates")
    for page in paginator.paginate(CertificateStatuses=["ISSUED", "PENDING_VALIDATION"]):
        for cert in page["CertificateSummaryList"]:
            if cert["DomainName"] == domain:
                return cert["CertificateArn"]
    return ""


@cogtainer.command("destroy")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def destroy_cmd(ctx: click.Context, profile: str | None, yes: bool):
    """Destroy a cogent's cogtainer infrastructure."""
    import os
    import subprocess

    from polis.aws import resolve_org_profile

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    profile = resolve_org_profile(profile)
    if not yes:
        click.confirm(f"This will destroy the stack for cogent-{name}. Continue?", abort=True)
    cmd = [
        "npx", "cdk", "destroy", f"cogent-{safe_name}-cogtainer",
        "-c", f"cogent_name={name}",
        "--app", "python -m cogtainer.cdk.app",
        "--force",
    ]
    env = {**os.environ, "AWS_PROFILE": profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("CDK destroy failed")
    click.echo(f"Cogtainer infrastructure for cogent-{name} destroyed.")


@cogtainer.command("build")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.pass_context
def build_cmd(ctx: click.Context, profile: str | None):
    """Build and push the executor Docker image to polis ECR."""
    import base64
    import subprocess

    from polis.aws import get_polis_session, resolve_org_profile, set_profile

    profile = resolve_org_profile(profile)
    set_profile(profile)

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    tag = f"executor-{safe_name}"

    # Get polis ECR repo URI
    polis_session, _ = get_polis_session()
    ecr_client = polis_session.client("ecr")
    repos = ecr_client.describe_repositories(repositoryNames=["cogent"])["repositories"]
    repo_uri = repos[0]["repositoryUri"]

    image = f"{repo_uri}:{tag}"
    click.echo(f"Building executor image: {image}")

    # Build
    result = subprocess.run(
        ["docker", "build", "--platform", "linux/amd64", "-f", "src/cogtainer/docker/Dockerfile", "-t", image, "."],
        capture_output=False,
    )
    if result.returncode != 0:
        raise click.ClickException("Docker build failed")

    # Login to ECR (auth token is base64-encoded "AWS:password")
    token = ecr_client.get_authorization_token()
    auth_data = token["authorizationData"][0]
    decoded = base64.b64decode(auth_data["authorizationToken"]).decode()
    password = decoded.split(":", 1)[1]
    registry = auth_data["proxyEndpoint"]
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password.encode(),
        capture_output=False,
    )

    # Push
    click.echo(f"Pushing {image}...")
    result = subprocess.run(["docker", "push", image], capture_output=False)
    if result.returncode != 0:
        raise click.ClickException("Docker push failed")

    click.echo(f"Image pushed: {image}")


# Wire in update subcommands
from cogtainer.update_cli import update  # noqa: E402

cogtainer.add_command(update)
