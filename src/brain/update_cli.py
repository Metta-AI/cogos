"""cogent brain update — update subcommands for individual components."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import time
import zipfile

import boto3
import click

from cli import DefaultCommandGroup, get_cogent_name

DEFAULT_REGION = "us-east-1"


class UpdateGroup(DefaultCommandGroup):
    """Update group that defaults to 'all'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, default_cmd="all", **kwargs)


@click.group(cls=UpdateGroup)
def update():
    """Update components of a running cogent.

    \b
    Default (no subcommand): update Lambda code + RDS migrations.
    """
    pass


def _get_session(profile: str | None = None) -> boto3.Session:
    """Get a boto3 session for the polis account (all brain resources live there)."""
    from polis.aws import get_polis_session, set_profile
    set_profile(profile or "softmax-org")
    session, _ = get_polis_session()
    return session


def _ensure_db_env(name: str) -> None:
    """Ensure DB_CLUSTER_ARN and DB_SECRET_ARN are set from CloudFormation stack in polis."""
    if os.environ.get("DB_CLUSTER_ARN") and os.environ.get("DB_SECRET_ARN"):
        return

    from polis.aws import get_polis_session, set_profile
    set_profile("softmax-org")
    session, _ = get_polis_session()

    safe_name = name.replace(".", "-")
    stack_name = f"cogent-{safe_name}-brain"
    cf = session.client("cloudformation", region_name=DEFAULT_REGION)

    resp = cf.describe_stacks(StackName=stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}

    if "ClusterArn" in outputs:
        os.environ["DB_CLUSTER_ARN"] = outputs["ClusterArn"]
    if "SecretArn" in outputs:
        os.environ["DB_SECRET_ARN"] = outputs["SecretArn"]

    # SecretArn may not be a stack output yet — look it up from resources
    if not os.environ.get("DB_SECRET_ARN"):
        resources = cf.list_stack_resources(StackName=stack_name)
        for r in resources.get("StackResourceSummaries", []):
            if "Secret" in r["LogicalResourceId"] and "Attachment" not in r["LogicalResourceId"]:
                if r["PhysicalResourceId"].startswith("arn:aws:secretsmanager:"):
                    os.environ["DB_SECRET_ARN"] = r["PhysicalResourceId"]
                    break

    # Export polis credentials so Repository's boto3 client can access RDS Data API
    creds = session.get_credentials().get_frozen_credentials()
    os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
    if creds.token:
        os.environ["AWS_SESSION_TOKEN"] = creds.token


def _package_lambda_code() -> bytes:
    """Zip the src/ directory for Lambda deployment."""
    src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src_dir):
            # Skip __pycache__, .pyc, test files
            if "__pycache__" in root or ".egg-info" in root:
                continue
            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                full_path = os.path.join(root, fname)
                arc_name = os.path.relpath(full_path, os.path.dirname(src_dir))
                zf.write(full_path, arc_name)
    return buf.getvalue()


@update.command("all")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--no-mind", is_flag=True, help="Skip mind update")
@click.pass_context
def update_all(ctx: click.Context, profile: str, no_mind: bool):
    """Update Lambda + DB migrations + mind sync (default)."""
    t0 = time.monotonic()
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_rds, profile=profile, force=False)
    if not no_mind:
        ctx.invoke(update_mind)
    click.echo(f"\nTotal: {time.monotonic() - t0:.1f}s")


@update.command("lambda")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_lambda(ctx: click.Context, profile: str):
    """Update Lambda function code."""
    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    session = _get_session(profile)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating cogent-{name} Lambda functions...")

    zip_bytes = _package_lambda_code()
    pkg_time = time.monotonic() - t0
    click.echo(f"  Package: {len(zip_bytes) / 1024:.0f} KB ({pkg_time:.1f}s)")

    lambda_client = session.client("lambda", region_name=DEFAULT_REGION)

    lambda_functions = [
        f"cogent-{safe_name}-orchestrator",
        f"cogent-{safe_name}-executor",
    ]

    for fn_name in lambda_functions:
        t1 = time.monotonic()
        try:
            lambda_client.update_function_code(
                FunctionName=fn_name,
                ZipFile=zip_bytes,
            )
            click.echo(f"  {fn_name}: {click.style('updated', fg='green')} ({time.monotonic() - t1:.1f}s)")
        except lambda_client.exceptions.ResourceNotFoundException:
            click.echo(f"  {fn_name}: {click.style('not found (skip)', fg='yellow')}")
        except Exception as e:
            click.echo(f"  {fn_name}: {click.style(str(e), fg='red')}")

    click.echo(f"  Lambda: {time.monotonic() - t0:.1f}s")


@update.command("ecs")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_ecs(ctx: click.Context, profile: str, skip_health: bool):
    """Force new ECS deployment (new container)."""
    name = get_cogent_name(ctx)
    session = _get_session(profile)
    safe_name = name.replace(".", "-")
    cluster_name = "cogent-polis"

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)

    # Find dashboard service for this cogent in the shared polis cluster
    try:
        service_arns = ecs_client.list_services(cluster=cluster_name)["serviceArns"]
    except Exception:
        click.echo(f"  No ECS cluster '{cluster_name}' found.")
        return

    # Match the dashboard service for this cogent
    service_arn = None
    for arn in service_arns:
        svc_name = arn.rsplit("/", 1)[-1]
        if safe_name in svc_name and ("DashService" in svc_name or "dashboard" in svc_name):
            service_arn = arn
            break

    if not service_arn:
        click.echo(f"  No dashboard ECS service found for cogent-{name} in {cluster_name}.")
        return

    click.echo(f"Forcing new ECS deployment for cogent-{name}...")
    click.echo(f"  Cluster: {cluster_name}")
    click.echo(f"  Service: {service_arn}")

    ecs_client.update_service(
        cluster=cluster_name,
        service=service_arn,
        forceNewDeployment=True,
    )

    if not skip_health:
        click.echo("  Waiting for service to stabilize...")
        try:
            waiter = ecs_client.get_waiter("services_stable")
            waiter.wait(cluster=cluster_name, services=[service_arn])
            click.echo(f"  ECS deployment for cogent-{name} completed.")
        except Exception as e:
            click.echo(f"  Service did not stabilize: {e}", err=True)
            sys.exit(1)
    else:
        click.echo(f"  ECS deployment for cogent-{name} initiated.")


@update.command("rds")
@click.option("--profile", default=None, help="AWS profile")
@click.option("--force", is_flag=True, help="Force re-run migrations")
@click.pass_context
def update_rds(ctx: click.Context, profile: str | None, force: bool):
    """Run database schema migrations via Data API."""
    from brain.db.migrations import apply_schema

    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    _ensure_db_env(name)
    click.echo(f"Running migrations for cogent-{name} via Data API...")
    version = apply_schema()
    click.echo(f"  Schema at version {version}. ({time.monotonic() - t0:.1f}s)")


@update.command("mind")
@click.pass_context
def update_mind(ctx: click.Context):
    """Sync mind (programs, tasks, memories) from egg directory."""
    from mind.cli import _ensure_db_env as _mind_ensure_db_env
    from mind.cli import mind_update

    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    _mind_ensure_db_env(name)
    click.echo("Syncing mind from egg directory...")
    ctx.invoke(mind_update, force=False)
    click.echo(f"  Mind: {time.monotonic() - t0:.1f}s")


@update.command("dashboard")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_dashboard(ctx: click.Context, skip_health: bool):
    """Build, push, and deploy the dashboard container."""
    import base64
    import subprocess

    from polis.aws import POLIS_ACCOUNT_ID, get_polis_session

    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    image_tag = f"{safe_name}-dashboard"
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    click.echo(f"Updating dashboard for cogent-{name}...")

    # 1. Build Docker image
    click.echo("  Building Docker image...")
    t1 = time.monotonic()
    result = subprocess.run(
        [
            "docker", "build",
            "-f", "dashboard/Dockerfile",
            "-t", f"cogent:{image_tag}",
            "--platform", "linux/amd64",
            ".",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(result.stderr[-500:] if result.stderr else "")
        raise click.ClickException("Docker build failed")
    click.echo(f"  Build: {click.style('ok', fg='green')} ({time.monotonic() - t1:.1f}s)")

    # 2. Get polis session with full admin (ECR push needs perms beyond cogent-polis-admin)
    from polis.aws import _assume_role
    org_session = boto3.Session(profile_name="softmax-org", region_name=DEFAULT_REGION)
    session = _assume_role(org_session, POLIS_ACCOUNT_ID, "OrganizationAccountAccessRole")
    ecr = session.client("ecr", region_name=DEFAULT_REGION)
    repo_uri = f"{POLIS_ACCOUNT_ID}.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/cogent"

    # Docker login to ECR
    click.echo("  Logging into ECR...")
    token_resp = ecr.get_authorization_token()
    auth = token_resp["authorizationData"][0]
    user_pass = base64.b64decode(auth["authorizationToken"]).decode()
    password = user_pass.split(":", 1)[1]
    login_result = subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", auth["proxyEndpoint"]],
        input=password,
        capture_output=True,
        text=True,
    )
    if login_result.returncode != 0:
        raise click.ClickException(f"ECR login failed: {login_result.stderr}")

    # 3. Tag and push
    click.echo("  Pushing image...")
    t1 = time.monotonic()
    remote_tag = f"{repo_uri}:{image_tag}"
    subprocess.run(["docker", "tag", f"cogent:{image_tag}", remote_tag], check=True)
    result = subprocess.run(["docker", "push", remote_tag], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(f"Docker push failed: {result.stderr[-300:]}")
    click.echo(f"  Push: {click.style('ok', fg='green')} ({time.monotonic() - t1:.1f}s)")

    # 4. Find the dashboard ECS service on cogent-polis cluster
    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)
    services = ecs_client.list_services(cluster="cogent-polis").get("serviceArns", [])
    dash_services = [s for s in services if safe_name in s]
    if not dash_services:
        raise click.ClickException(f"No dashboard service found for {safe_name} on cogent-polis cluster")
    service_arn = dash_services[0]

    # 5. Get current task definition, update image, register new revision
    click.echo("  Updating task definition...")
    svc_desc = ecs_client.describe_services(cluster="cogent-polis", services=[service_arn])["services"][0]
    task_def_arn = svc_desc["taskDefinition"]
    task_def = ecs_client.describe_task_definition(taskDefinition=task_def_arn)["taskDefinition"]

    # Update the container image
    containers = task_def["containerDefinitions"]
    for c in containers:
        if c.get("name") == "web":
            c["image"] = remote_tag
            break
    else:
        # If no "web" container, update the first one
        containers[0]["image"] = remote_tag

    # Register new task definition revision
    register_kwargs = {
        "family": task_def["family"],
        "containerDefinitions": containers,
        "taskRoleArn": task_def.get("taskRoleArn", ""),
        "executionRoleArn": task_def.get("executionRoleArn", ""),
        "networkMode": task_def.get("networkMode", "awsvpc"),
        "requiresCompatibilities": task_def.get("requiresCompatibilities", ["FARGATE"]),
        "cpu": task_def.get("cpu", "256"),
        "memory": task_def.get("memory", "512"),
    }
    # Only include runtimePlatform if present
    if "runtimePlatform" in task_def:
        register_kwargs["runtimePlatform"] = task_def["runtimePlatform"]

    new_td = ecs_client.register_task_definition(**register_kwargs)
    new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
    click.echo(f"  Task definition: {new_td_arn.split('/')[-1]}")

    # 6. Update service with new task definition
    click.echo("  Deploying...")
    ecs_client.update_service(
        cluster="cogent-polis",
        service=service_arn,
        taskDefinition=new_td_arn,
        forceNewDeployment=True,
    )

    if not skip_health:
        click.echo("  Waiting for service to stabilize...")
        try:
            waiter = ecs_client.get_waiter("services_stable")
            waiter.wait(
                cluster="cogent-polis",
                services=[service_arn],
                WaiterConfig={"Delay": 10, "MaxAttempts": 60},
            )
            click.echo(f"  Dashboard: {click.style('deployed', fg='green')} ({time.monotonic() - t0:.1f}s)")
        except Exception as e:
            click.echo(f"  Service did not stabilize: {e}", err=True)
            click.echo("  The deployment is still in progress. Check ECS console.")
    else:
        click.echo(f"  Dashboard deployment initiated. ({time.monotonic() - t0:.1f}s)")


@update.command("stack")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_stack(ctx: click.Context, profile: str):
    """Full CDK stack update (rebuilds dashboard container)."""
    import subprocess

    from polis.aws import get_polis_session, set_profile

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")

    # Look up certificate ARN from polis account
    set_profile(profile)
    session, _ = get_polis_session()
    acm = session.client("acm", region_name=DEFAULT_REGION)
    cert_arn = ""
    domain = f"{safe_name}.softmax-cogents.com"
    for cert in acm.list_certificates()["CertificateSummaryList"]:
        if cert["DomainName"] == domain:
            cert_arn = cert["CertificateArn"]
            break

    # Look up ECR repo URI
    ecr_repo_uri = ""
    try:
        ecr_client = session.client("ecr")
        repos = ecr_client.describe_repositories(repositoryNames=["cogent"])["repositories"]
        ecr_repo_uri = repos[0]["repositoryUri"]
    except Exception:
        click.echo("Warning: Could not resolve polis ECR repo. Using default image.")

    click.echo(f"Updating CDK stack for cogent-{name}...")
    cmd = [
        "cdk",
        "deploy",
        f"cogent-{safe_name}-brain",
        "-c", f"cogent_name={name}",
        "-c", f"certificate_arn={cert_arn}",
        "-c", f"ecr_repo_uri={ecr_repo_uri}",
        "--app", "python -m brain.cdk.app",
        "--require-approval", "never",
    ]
    env = {**os.environ, "AWS_PROFILE": profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")
    click.echo(f"Stack update for cogent-{name} completed.")
