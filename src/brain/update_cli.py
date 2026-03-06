"""cogent brain update — update subcommands for individual components."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import zipfile

import boto3
import click

from brain.cli import DefaultCommandGroup, get_cogent_name

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
    """Get a boto3 session for the brain account (current AWS account)."""
    if profile and profile != "softmax-org":
        return boto3.Session(profile_name=profile, region_name=DEFAULT_REGION)
    # Default: use current credentials (brain resources are in the cogent account, not org)
    return boto3.Session(region_name=DEFAULT_REGION)


def _ensure_db_env(name: str) -> None:
    """Ensure DB_CLUSTER_ARN and DB_SECRET_ARN are set from CloudFormation stack."""
    if os.environ.get("DB_CLUSTER_ARN") and os.environ.get("DB_SECRET_ARN"):
        return

    safe_name = name.replace(".", "-")
    stack_name = f"cogent-{safe_name}-brain"
    cf = boto3.client("cloudformation", region_name=DEFAULT_REGION)

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
@click.pass_context
def update_all(ctx: click.Context, profile: str):
    """Update Lambda + DB migrations (default)."""
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_rds, profile=profile, force=False)


@update.command("lambda")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_lambda(ctx: click.Context, profile: str):
    """Update Lambda function code."""
    name = get_cogent_name(ctx)
    session = _get_session(profile)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating cogent-{name} Lambda functions...")

    click.echo("  Packaging Lambda code...")
    zip_bytes = _package_lambda_code()
    click.echo(f"  Package size: {len(zip_bytes) / 1024:.0f} KB")

    lambda_client = session.client("lambda", region_name=DEFAULT_REGION)

    lambda_functions = [
        f"cogent-{safe_name}-orchestrator",
        f"cogent-{safe_name}-executor",
    ]

    for fn_name in lambda_functions:
        try:
            lambda_client.update_function_code(
                FunctionName=fn_name,
                ZipFile=zip_bytes,
            )
            click.echo(f"  {fn_name}: {click.style('updated', fg='green')}")
        except lambda_client.exceptions.ResourceNotFoundException:
            click.echo(f"  {fn_name}: {click.style('not found (skip)', fg='yellow')}")
        except Exception as e:
            click.echo(f"  {fn_name}: {click.style(str(e), fg='red')}")

    click.echo(f"  Lambda update for cogent-{name} completed.")


@update.command("ecs")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_ecs(ctx: click.Context, profile: str, skip_health: bool):
    """Force new ECS deployment (new container)."""
    name = get_cogent_name(ctx)
    session = _get_session(profile)
    safe_name = name.replace(".", "-")
    cluster_name = f"cogent-{safe_name}"

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)

    # Find services in the cluster
    try:
        services = ecs_client.list_services(cluster=cluster_name)["serviceArns"]
    except Exception:
        click.echo(f"  No ECS cluster found for cogent-{name}.")
        click.echo("  This cogent may be in serverless mode. Use 'update lambda' instead.")
        return

    if not services:
        click.echo(f"  No ECS services found in cluster {cluster_name}.")
        return

    service_arn = services[0]
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

    name = get_cogent_name(ctx)
    _ensure_db_env(name)
    click.echo(f"Running migrations for cogent-{name} via Data API...")
    version = apply_schema()
    click.echo(f"  Schema at version {version}.")


@update.command("stack")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_stack(ctx: click.Context, profile: str):
    """Full CDK stack update."""
    import subprocess

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    click.echo(f"Updating CDK stack for cogent-{name}...")
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
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")
    click.echo(f"Stack update for cogent-{name} completed.")
