"""cogent cogtainer update — update subcommands for individual components."""

from __future__ import annotations

import io
import os
import sys
import time
import zipfile

import boto3
import click

from cli import DefaultCommandGroup, get_cogent_name
# Discord bridge is now polis-level; per-cogent bridge management removed
from polis import naming
from polis.aws import DEFAULT_ORG_PROFILE, DEFAULT_REGION, ORG_PROFILE_ENV, resolve_org_profile, set_org_profile
from polis.config import PolisConfig

_PROFILE_HELP = f"AWS profile (default: ${ORG_PROFILE_ENV} or {DEFAULT_ORG_PROFILE})"


def _check_ecr_image_for_commit(session: boto3.Session, prefix: str = "executor") -> str | None:
    """Check that an ECR image exists for the current git commit.

    Returns the matching tag if found, or None. Prints a warning if no image
    matches the current commit.
    """
    import subprocess

    try:
        sha_short = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None

    expected_tag = f"{prefix}-{sha_short}"

    ecr_client = session.client("ecr", region_name=DEFAULT_REGION)
    try:
        ecr_client.describe_images(
            repositoryName=naming.ecr_repo_name(),
            imageIds=[{"imageTag": expected_tag}],
        )
        click.echo(f"  ECR image for HEAD ({sha_short}): {click.style('found', fg='green')}")
        return expected_tag
    except Exception:
        click.echo(
            click.style(
                f"  Warning: No ECR image found for current commit ({sha_short}).\n"
                f"  Expected tag: {expected_tag}\n"
                f"  Check CI: gh run list --repo Metta-AI/cogents-v1 --workflow docker-build-{prefix}.yml\n"
                f"  The deployed code may not match the running container.",
                fg="yellow",
            )
        )
        return None


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
    """Get a boto3 session for the polis account (all cogtainer resources live there)."""
    from polis.aws import get_polis_session

    set_org_profile(profile)
    session, _ = get_polis_session()
    return session


def _ensure_db_env(name: str, profile: str | None = None) -> None:
    """Ensure DB_CLUSTER_ARN and DB_SECRET_ARN are set from the shared polis Aurora cluster."""
    if os.environ.get("DB_CLUSTER_ARN") and os.environ.get("DB_SECRET_ARN"):
        return

    from polis.aws import get_polis_session

    set_org_profile(profile)
    session, _ = get_polis_session()

    cf = session.client("cloudformation", region_name=DEFAULT_REGION)

    resp = cf.describe_stacks(StackName=naming.polis_stack_name())
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}

    if "SharedDbClusterArn" in outputs:
        os.environ["DB_CLUSTER_ARN"] = outputs["SharedDbClusterArn"]
    if "SharedDbSecretArn" in outputs:
        os.environ["DB_SECRET_ARN"] = outputs["SharedDbSecretArn"]

    safe_name = name.replace(".", "-").replace("-", "_")
    os.environ.setdefault("DB_NAME", f"cogent_{safe_name}")

    creds = session.get_credentials().get_frozen_credentials()
    os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
    if creds.token:
        os.environ["AWS_SESSION_TOKEN"] = creds.token


def _package_lambda_code() -> bytes:
    """Zip the src/ directory with pip-installed dependencies for Lambda deployment.

    The Lambda handler expects top-level packages (cogtainer/, memory/, etc.) without
    a src/ prefix, so we use src_dir as the base for archive paths.  Dependencies
    are installed into a temporary directory and bundled into the same zip.
    """
    import subprocess
    import tempfile

    src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)))
    project_root = os.path.dirname(src_dir)

    # Install runtime deps into a temp directory
    deps_dir = tempfile.mkdtemp(prefix="lambda-deps-")
    lambda_deps = [
        "pydantic",
        "pydantic-settings",
        "pydantic-core",
        "annotated-types",
        "Pillow",
        "google-genai",
        "anthropic",
        "asana",
        "PyGithub",
    ]
    subprocess.check_call(
        [
            "uv",
            "pip",
            "install",
            "--target",
            deps_dir,
            "--quiet",
            "--python",
            "3.12",
            "--python-platform",
            "linux",
        ]
        + lambda_deps,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add source code (cogtainer/, memory/, channels/, polis/, etc.)
        for root, _dirs, files in os.walk(src_dir):
            if "__pycache__" in root or ".egg-info" in root:
                continue
            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                full_path = os.path.join(root, fname)
                arc_name = os.path.relpath(full_path, src_dir)
                zf.write(full_path, arc_name)
        # Add dependencies
        for root, _dirs, files in os.walk(deps_dir):
            if "__pycache__" in root:
                continue
            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                full_path = os.path.join(root, fname)
                arc_name = os.path.relpath(full_path, deps_dir)
                zf.write(full_path, arc_name)

    import shutil

    shutil.rmtree(deps_dir, ignore_errors=True)
    return buf.getvalue()


@update.command("all")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.pass_context
def update_all(ctx: click.Context, profile: str | None):
    """Update Lambda + DB migrations (default)."""
    profile = resolve_org_profile(profile)
    t0 = time.monotonic()
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_rds, profile=profile, force=False)
    click.echo(f"\nTotal: {time.monotonic() - t0:.1f}s")


def _read_boot_versions(name: str) -> dict[str, str] | None:
    """Read versions.json from the cogent's database via FileStore."""
    try:
        _ensure_db_env(name)
        import json as _json

        from cogos.db.repository import Repository
        from cogos.files.store import FileStore
        repo = Repository.create()
        fs = FileStore(repo)
        content = fs.get_content("mnt/boot/versions.json")
        if content:
            return _json.loads(content).get("components", {})
    except Exception:
        pass
    return None


@update.command("lambda")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--sha", default=None, help="Use pre-built lambda zip from CI (git SHA)")
@click.pass_context
def update_lambda(ctx: click.Context, profile: str | None, sha: str | None):
    """Update Lambda function code."""
    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    session = _get_session(profile)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating cogent-{name} Lambda functions...")
    _check_ecr_image_for_commit(session, "executor")

    if not sha:
        versions = _read_boot_versions(name)
        if versions and versions.get("lambda") and versions["lambda"] != "local":
            sha = versions["lambda"]
            click.echo(f"  Using lambda version from boot manifest: {sha[:8]}")

    if sha:
        full_sha = _resolve_commit_sha(sha)
        s3_key = f"lambda/{full_sha}/lambda.zip"
        click.echo(f"  Downloading pre-built lambda from CI ({sha[:8]})...")
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            _download_ci_artifact(session, s3_key, tmp_path)
            with open(tmp_path, "rb") as f:
                zip_bytes = f.read()
        except Exception:
            raise click.ClickException(
                f"CI artifact not found: s3://{CI_ARTIFACTS_BUCKET}/{s3_key}\n"
                f"Check CI: gh run list --repo Metta-AI/cogents-v1 --workflow docker-build-executor.yml"
            )
        finally:
            os.unlink(tmp_path)
    else:
        zip_bytes = _package_lambda_code()
    pkg_time = time.monotonic() - t0
    click.echo(f"  Package: {len(zip_bytes) / 1024:.0f} KB ({pkg_time:.1f}s)")

    lambda_client = session.client("lambda", region_name=DEFAULT_REGION)

    lambda_functions = [
        f"cogent-{safe_name}-orchestrator",
        f"cogent-{safe_name}-executor",
        f"cogent-{safe_name}-dispatcher",
        f"cogent-{safe_name}-ingress",
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

    # Record content deploy timestamp
    try:
        _ensure_db_env(name)
        from cogos.db.repository import Repository

        repo = Repository.create()
        repo.set_meta("content:deployed_at")
    except Exception:
        pass

    click.echo(f"  Lambda: {time.monotonic() - t0:.1f}s")


def _find_ecs_service(ecs_client, safe_name: str, service_type: str = "dashboard") -> str | None:
    """Find an ECS service for a cogent by type (dashboard or discord)."""
    cluster = "cogent-polis"
    try:
        service_arns = ecs_client.list_services(cluster=cluster)["serviceArns"]
    except Exception:
        return None

    for arn in service_arns:
        svc_name = arn.rsplit("/", 1)[-1]
        if safe_name not in svc_name:
            continue
        if service_type == "dashboard" and ("DashService" in svc_name or "dashboard" in svc_name):
            return arn
        if service_type == "discord" and "discord" in svc_name:
            return arn
    return None


def _update_ecs_image(ecs_client, session, service_arn: str, tag: str) -> str:
    """Verify ECR tag exists, update task definition with new image, return new task def ARN."""
    from polis.aws import POLIS_ACCOUNT_ID

    repo_uri = f"{POLIS_ACCOUNT_ID}.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/cogent"
    new_image = f"{repo_uri}:{tag}"
    click.echo(f"  Image: {new_image}")

    # Verify the tag exists in ECR
    ecr_client = session.client("ecr", region_name=DEFAULT_REGION)
    try:
        ecr_client.describe_images(
            repositoryName=naming.ecr_repo_name(),
            imageIds=[{"imageTag": tag}],
        )
        click.echo(f"  ECR tag '{tag}': {click.style('found', fg='green')}")
    except Exception:
        # Determine the right workflow name from the tag prefix
        prefix = tag.split("-")[0] if "-" in tag else tag
        raise click.ClickException(
            f"ECR tag '{tag}' not found in cogent repo. "
            f"Check CI build status: gh run list --repo Metta-AI/cogents-v1 --workflow docker-build-{prefix}.yml"
        )

    svc_desc = ecs_client.describe_services(cluster="cogent-polis", services=[service_arn])["services"][0]
    task_def_arn = svc_desc["taskDefinition"]
    task_def = ecs_client.describe_task_definition(taskDefinition=task_def_arn)["taskDefinition"]

    containers = task_def["containerDefinitions"]
    containers[0]["image"] = new_image

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
    if "runtimePlatform" in task_def:
        register_kwargs["runtimePlatform"] = task_def["runtimePlatform"]

    new_td = ecs_client.register_task_definition(**register_kwargs)
    new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
    click.echo(f"  Task definition: {new_td_arn.split('/')[-1]}")
    return new_td_arn


@update.command("ecs")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.option("--tag", default=None, help="ECR image tag to deploy (e.g. dashboard-abc1234, dashboard-latest)")
@click.pass_context
def update_ecs(ctx: click.Context, profile: str | None, skip_health: bool, tag: str | None):
    """Force new ECS deployment for the dashboard service.

    \b
    Use --tag to deploy a specific CI-built image:
      cogent <name> cogtainer update ecs --tag dashboard-abc1234
      cogent <name> cogtainer update ecs --tag dashboard-latest

    Tags prefixed with 'executor-' are rejected — executors run as
    Lambda, not ECS. Use 'cogtainer update lambda' instead.
    """
    if tag and tag.startswith("executor-"):
        raise click.ClickException(
            "Executor images run as Lambda, not ECS. Use 'cogtainer update lambda' to deploy executor code."
        )

    name = get_cogent_name(ctx)

    if not tag:
        versions = _read_boot_versions(name)
        if versions and versions.get("dashboard") and versions["dashboard"] != "local":
            tag = f"dashboard-{versions['dashboard']}"
            click.echo(f"  Using dashboard version from boot manifest: {tag}")
    session = _get_session(profile)
    safe_name = name.replace(".", "-")
    cluster_name = "cogent-polis"

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)

    service_arn = _find_ecs_service(ecs_client, safe_name, "dashboard")
    if not service_arn:
        click.echo(f"  No dashboard ECS service found for cogent-{name} in {cluster_name}.")
        return

    click.echo(f"Forcing new ECS deployment for cogent-{name}...")
    click.echo(f"  Cluster: {cluster_name}")
    click.echo(f"  Service: {service_arn}")

    update_kwargs: dict = {
        "cluster": cluster_name,
        "service": service_arn,
        "forceNewDeployment": True,
    }

    if tag:
        new_td_arn = _update_ecs_image(ecs_client, session, service_arn, tag)
        update_kwargs["taskDefinition"] = new_td_arn

    ecs_client.update_service(**update_kwargs)

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
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--force", is_flag=True, help="Force re-run migrations")
@click.pass_context
def update_rds(ctx: click.Context, profile: str | None, force: bool):
    """Run database schema migrations via Data API."""
    from cogos.db.migrations import apply_cogos_sql_migrations, apply_schema
    from cogos.db.repository import Repository

    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    _ensure_db_env(name, profile)
    click.echo(f"Running migrations for cogent-{name} via Data API...")
    version = apply_schema()
    repo = Repository.create(
        resource_arn=os.environ.get("DB_CLUSTER_ARN") or os.environ.get("DB_RESOURCE_ARN"),
        secret_arn=os.environ.get("DB_SECRET_ARN"),
        database=os.environ.get("DB_NAME", "cogent"),
        region=os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION),
    )
    statements = apply_cogos_sql_migrations(repo)

    # Record schema migration timestamp
    try:
        repo.set_meta("schema:migrated_at", str(version))
    except Exception:
        pass

    click.echo(f"  Schema at version {version}.")
    click.echo(f"  CogOS SQL migrations applied ({statements} statements). ({time.monotonic() - t0:.1f}s)")


def _get_polis_admin_session(profile: str | None = None):
    """Get a polis session with full admin (OrganizationAccountAccessRole)."""
    from polis.aws import POLIS_ACCOUNT_ID, _assume_role

    resolved_profile = resolve_org_profile(profile)
    org_session = boto3.Session(profile_name=resolved_profile, region_name=DEFAULT_REGION)
    return _assume_role(org_session, POLIS_ACCOUNT_ID, "OrganizationAccountAccessRole")


def _dashboard_project_root() -> str:
    """Return the repository root for dashboard build operations."""
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _dashboard_frontend_dir(project_root: str | None = None) -> str:
    """Return the Next.js frontend directory."""
    root = project_root or _dashboard_project_root()
    return os.path.join(root, "dashboard", "frontend")


def _sessions_bucket_name(safe_name: str) -> str:
    """Return the deterministic sessions bucket name for a cogent."""
    return f"cogent-{safe_name}-cogtainer-sessions"


def _build_dashboard_tarball(project_root: str | None = None) -> tuple[str, float]:
    """Build and package the dashboard frontend into a tarball."""
    import subprocess
    import tarfile
    import tempfile

    frontend_dir = _dashboard_frontend_dir(project_root)

    click.echo("  Building Next.js...")
    t1 = time.monotonic()
    result = subprocess.run(
        ["npx", "next", "build"],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(result.stderr[-500:] if result.stderr else result.stdout[-500:])
        raise click.ClickException("Next.js build failed")
    click.echo(f"  Build: {click.style('ok', fg='green')} ({time.monotonic() - t1:.1f}s)")

    click.echo("  Packaging assets...")
    t1 = time.monotonic()
    standalone_dir = os.path.join(frontend_dir, ".next", "standalone")
    static_dir = os.path.join(frontend_dir, ".next", "static")
    public_dir = os.path.join(frontend_dir, "public")

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tarball_path = tmp.name
        with tarfile.open(tarball_path, "w:gz") as tar:
            for entry in os.listdir(standalone_dir):
                tar.add(os.path.join(standalone_dir, entry), arcname=entry)
            if os.path.isdir(static_dir):
                tar.add(static_dir, arcname=".next/static")
            if os.path.isdir(public_dir):
                tar.add(public_dir, arcname="public")

    size_mb = os.path.getsize(tarball_path) / (1024 * 1024)
    click.echo(f"  Package: {size_mb:.1f} MB ({time.monotonic() - t1:.1f}s)")
    return tarball_path, size_mb


def _upload_dashboard_tarball(
    session: boto3.Session,
    bucket: str,
    tarball_path: str,
    s3_key: str = "dashboard/frontend.tar.gz",
) -> str:
    """Upload dashboard assets to the cogent sessions bucket."""
    s3_client = session.client("s3", region_name=DEFAULT_REGION)
    s3_client.upload_file(tarball_path, bucket, s3_key)
    return f"s3://{bucket}/{s3_key}"


CI_ARTIFACTS_BUCKET = "cogent-polis-ci-artifacts"


def _resolve_commit_sha(sha: str) -> str:
    """Resolve a short or long SHA to the full SHA used in CI artifacts."""
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", sha], text=True
        ).strip()
    except Exception:
        return sha


def _download_ci_artifact(session: boto3.Session, s3_key: str, dest_path: str) -> None:
    """Download a CI artifact from the shared bucket."""
    s3_client = session.client("s3", region_name=DEFAULT_REGION)
    s3_client.download_file(CI_ARTIFACTS_BUCKET, s3_key, dest_path)


def _check_ci_artifact_exists(session: boto3.Session, s3_key: str) -> bool:
    """Check if a CI artifact exists in the shared bucket."""
    s3_client = session.client("s3", region_name=DEFAULT_REGION)
    try:
        s3_client.head_object(Bucket=CI_ARTIFACTS_BUCKET, Key=s3_key)
        return True
    except Exception:
        return False


def _wait_for_bucket(
    session: boto3.Session,
    bucket: str,
    *,
    timeout_s: int = 900,
    poll_s: int = 5,
) -> bool:
    """Poll until the sessions bucket exists and is accessible."""
    s3_client = session.client("s3", region_name=DEFAULT_REGION)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            s3_client.head_bucket(Bucket=bucket)
            return True
        except Exception:
            time.sleep(poll_s)
    return False


def _get_sessions_bucket(session, safe_name: str) -> str:
    """Look up the sessions S3 bucket for a cogent from its CloudFormation stack."""
    cf = session.client("cloudformation", region_name=DEFAULT_REGION)
    stack_name = f"cogent-{safe_name}-cogtainer"
    resp = cf.describe_stacks(StackName=stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
    bucket = outputs.get("SessionsBucket")
    if not bucket:
        raise click.ClickException(f"SessionsBucket not found in stack {stack_name} outputs")
    return bucket


def _is_dashboard_service_name(service_name: str, safe_name: str) -> bool:
    """Return True when the ECS service name belongs to the dashboard."""
    return safe_name in service_name and ("DashService" in service_name or "dashboard" in service_name)


def _find_dashboard_service(ecs_client, safe_name: str) -> str:
    """Find the dashboard ECS service ARN on cogent-polis cluster."""
    services = ecs_client.list_services(cluster="cogent-polis").get("serviceArns", [])
    dash_services = [s for s in services if _is_dashboard_service_name(s.rsplit("/", 1)[-1], safe_name)]
    if not dash_services:
        raise click.ClickException(f"No dashboard service found for {safe_name} on cogent-polis cluster")
    return dash_services[0]


def _get_discord_desired_count(session: boto3.Session, name: str) -> int | None:
    """No-op: Discord bridge is now polis-level."""
    return None


def _ensure_discord_bridge_state(
    session: boto3.Session,
    name: str,
    safe_name: str,
    *,
    previous_desired_count: int | None,
) -> tuple[str, int] | None:
    """No-op: Discord bridge is now polis-level."""
    return None


def _restart_ecs_service(ecs_client, service_arn: str, skip_health: bool, t0: float):
    """Force a new ECS deployment and optionally wait for stability."""
    click.echo("  Restarting ECS service...")
    ecs_client.update_service(
        cluster="cogent-polis",
        service=service_arn,
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


def _read_docker_version(project_root: str) -> str:
    """Read the dashboard Docker version from DOCKER_VERSION file."""
    version_file = os.path.join(project_root, "dashboard", "DOCKER_VERSION")
    if os.path.exists(version_file):
        return open(version_file).read().strip()
    return "0"


def _get_deployed_docker_version(ecs_client, service_arn: str) -> str:
    """Read the DOCKER_VERSION label from the currently deployed container."""
    svc_desc = ecs_client.describe_services(cluster="cogent-polis", services=[service_arn])["services"][0]
    task_def_arn = svc_desc["taskDefinition"]
    task_def = ecs_client.describe_task_definition(taskDefinition=task_def_arn)["taskDefinition"]
    for c in task_def.get("containerDefinitions", []):
        for env in c.get("environment", []):
            if env["name"] == "DASHBOARD_DOCKER_VERSION":
                return env["value"]
    return "0"


@update.command("dashboard")
@click.option("--docker", is_flag=True, help="Force rebuild and push Docker image")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.option("--sha", default=None, help="Use pre-built frontend from CI (git SHA)")
@click.pass_context
def update_dashboard(ctx: click.Context, docker: bool, skip_health: bool, sha: str | None):
    """Build frontend, upload to S3, and restart the dashboard.

    \b
    Default: build Next.js → tar.gz → S3 → restart ECS (~30s).
    Auto-detects when DOCKER_VERSION changes and rebuilds image.
    --docker: force rebuild Docker image + push ECR + update task def.
    """
    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    project_root = _dashboard_project_root()

    click.echo(f"Updating dashboard for cogent-{name}...")
    session = _get_polis_admin_session()

    # Auto-detect if Docker rebuild is needed
    if not docker:
        local_version = _read_docker_version(project_root)
        ecs_client = session.client("ecs", region_name=DEFAULT_REGION)
        service_arn = _find_dashboard_service(ecs_client, safe_name)
        deployed_version = _get_deployed_docker_version(ecs_client, service_arn)
        if local_version != deployed_version:
            click.echo(f"  Docker version changed: {deployed_version} → {local_version}")
            docker = True

    if docker:
        _docker_build_push_deploy(ctx, session, name, safe_name, project_root, skip_health, t0)
        return

    # --- Fast path: build frontend → S3 → restart ---
    _build_and_upload_frontend(session, safe_name, project_root, sha=sha)

    # 4. Signal running container to reload frontend (no ECS restart needed)
    click.echo("  Reloading frontend...")
    t1 = time.monotonic()
    reload_url = f"https://{safe_name}.{PolisConfig().domain}/admin/reload-frontend"
    try:
        import json
        import urllib.request

        # Load Cloudflare Access service token + dashboard API key
        sm = session.client("secretsmanager", region_name=DEFAULT_REGION)
        cf_token = json.loads(sm.get_secret_value(SecretId="cogent/polis/cloudflare-service-token")["SecretString"])
        api_key = json.loads(sm.get_secret_value(SecretId=f"cogent/{name}/dashboard-api-key")["SecretString"])[
            "api_key"
        ]

        req = urllib.request.Request(reload_url, method="POST")
        req.add_header("CF-Access-Client-Id", cf_token["client_id"])
        req.add_header("CF-Access-Client-Secret", cf_token["client_secret"])
        req.add_header("X-Api-Key", api_key)
        req.add_header("User-Agent", "cogent-cli/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
        click.echo(f"  Reload: {click.style('ok', fg='green')} ({time.monotonic() - t1:.1f}s)")
    except Exception as e:
        raise click.ClickException(f"Frontend reload failed: {e}")

    # 5. Purge Cloudflare cache so browsers get the new build
    click.echo("  Purging CDN cache...")
    t1 = time.monotonic()
    try:
        from polis.cloudflare import purge_cache
        from polis.secrets.store import SecretStore

        store = SecretStore(session=session)
        purge_cache(store)
        click.echo(f"  Cache: {click.style('purged', fg='green')} ({time.monotonic() - t1:.1f}s)")
    except Exception as e:
        click.echo(f"  Cache purge failed: {e}")

    click.echo(f"  Dashboard: {click.style('deployed', fg='green')} ({time.monotonic() - t0:.1f}s)")


def _build_and_upload_frontend(session, safe_name, project_root, sha: str | None = None):
    """Build Next.js frontend and upload tarball to S3."""
    # 1. Build Next.js and package standalone output
    if sha:
        full_sha = _resolve_commit_sha(sha)
        s3_key = f"dashboard/{full_sha}/frontend.tar.gz"
        click.echo(f"  Downloading pre-built frontend from CI ({sha[:8]})...")
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tarball_path = tmp.name
        try:
            _download_ci_artifact(session, s3_key, tarball_path)
        except Exception:
            raise click.ClickException(
                f"CI artifact not found: s3://{CI_ARTIFACTS_BUCKET}/{s3_key}\n"
                f"Check CI: gh run list --repo Metta-AI/cogents-v1 --workflow docker-build-dashboard.yml"
            )
    else:
        tarball_path, _size_mb = _build_dashboard_tarball(project_root)

    # 2. Upload to S3
    click.echo("  Uploading to S3...")
    t1 = time.monotonic()
    bucket = _get_sessions_bucket(session, safe_name)
    try:
        s3_uri = _upload_dashboard_tarball(session, bucket, tarball_path)
    finally:
        os.unlink(tarball_path)
    click.echo(f"  Upload: {s3_uri} ({time.monotonic() - t1:.1f}s)")


def _docker_build_push_deploy(ctx, session, name, safe_name, project_root, skip_health, t0):
    """Full Docker rebuild: build image → push ECR → update task def → deploy."""
    import base64
    import subprocess

    from polis.aws import POLIS_ACCOUNT_ID

    # Build and upload frontend assets to S3 first
    _build_and_upload_frontend(session, safe_name, project_root)

    image_tag = f"{safe_name}-dashboard"

    # 1. Build Docker image
    click.echo("  Building Docker image...")
    t1 = time.monotonic()
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            "dashboard/Dockerfile",
            "-t",
            f"cogent:{image_tag}",
            "--platform",
            "linux/amd64",
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

    # 2. ECR login
    ecr = session.client("ecr", region_name=DEFAULT_REGION)
    repo_uri = f"{POLIS_ACCOUNT_ID}.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/cogent"
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

    # 4. Update task definition with new image
    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)
    service_arn = _find_dashboard_service(ecs_client, safe_name)

    click.echo("  Updating task definition...")
    svc_desc = ecs_client.describe_services(cluster="cogent-polis", services=[service_arn])["services"][0]
    task_def_arn = svc_desc["taskDefinition"]
    task_def = ecs_client.describe_task_definition(taskDefinition=task_def_arn)["taskDefinition"]

    local_version = _read_docker_version(project_root)
    containers = task_def["containerDefinitions"]
    for c in containers:
        if c.get("name") == "web":
            c["image"] = remote_tag
            # Inject/update env vars needed for S3-based frontend and version detection
            env_list = c.setdefault("environment", [])
            bucket = next((e["value"] for e in env_list if e["name"] == "SESSIONS_BUCKET"), None)
            inject = {
                "DASHBOARD_DOCKER_VERSION": local_version,
            }
            if bucket:
                inject["DASHBOARD_ASSETS_S3"] = f"s3://{bucket}/dashboard/frontend.tar.gz"
            for key, val in inject.items():
                for env in env_list:
                    if env["name"] == key:
                        env["value"] = val
                        break
                else:
                    env_list.append({"name": key, "value": val})
            break
    else:
        containers[0]["image"] = remote_tag

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
    if "runtimePlatform" in task_def:
        register_kwargs["runtimePlatform"] = task_def["runtimePlatform"]

    new_td = ecs_client.register_task_definition(**register_kwargs)
    new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
    click.echo(f"  Task definition: {new_td_arn.split('/')[-1]}")

    # 5. Deploy
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
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.pass_context
def update_stack(ctx: click.Context, profile: str | None):
    """Full CDK stack update (rebuilds dashboard container)."""
    import subprocess

    from polis.aws import get_polis_session, resolve_org_profile, set_profile

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    profile = resolve_org_profile(profile)

    # Look up certificate ARN from polis account
    set_profile(profile)
    session, _ = get_polis_session()
    acm = session.client("acm", region_name=DEFAULT_REGION)
    cert_arn = ""
    domain = f"{safe_name}.{PolisConfig().domain}"
    for cert in acm.list_certificates()["CertificateSummaryList"]:
        if cert["DomainName"] == domain:
            cert_arn = cert["CertificateArn"]
            break

    # Look up ECR repo URI
    ecr_repo_uri = ""
    try:
        ecr_client = session.client("ecr")
        repos = ecr_client.describe_repositories(repositoryNames=[naming.ecr_repo_name()])["repositories"]
        ecr_repo_uri = repos[0]["repositoryUri"]
    except Exception:
        click.echo("Warning: Could not resolve polis ECR repo. Using default image.")

    discord_desired_count = _get_discord_desired_count(session, name)

    click.echo(f"Updating CDK stack for cogent-{name}...")
    cmd = [
        "npx",
        "cdk",
        "deploy",
        f"cogent-{safe_name}-cogtainer",
        "-c",
        f"cogent_name={name}",
        "-c",
        f"certificate_arn={cert_arn}",
        "-c",
        f"ecr_repo_uri={ecr_repo_uri}",
        "--app",
        "python -m cogtainer.cdk.app",
        "--require-approval",
        "never",
    ]
    env = {**os.environ, "AWS_PROFILE": profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")
    try:
        discord_action = _ensure_discord_bridge_state(
            session,
            name,
            safe_name,
            previous_desired_count=discord_desired_count,
        )
    except Exception as e:
        click.echo(f"Warning: could not reconcile Discord bridge state: {e}")
    else:
        if discord_action == ("restored", discord_desired_count):
            click.echo(f"Restoring Discord bridge desired count to {discord_desired_count} for cogent-{name}...")
        elif discord_action == ("autostarted", 1):
            click.echo(f"Starting Discord bridge for cogent-{name} because a token is configured...")

    # Record stack update timestamp
    try:
        _ensure_db_env(name)
        from cogos.db.repository import Repository

        repo = Repository.create()
        repo.set_meta("stack:updated_at")
    except Exception:
        pass

    click.echo(f"Stack update for cogent-{name} completed.")
