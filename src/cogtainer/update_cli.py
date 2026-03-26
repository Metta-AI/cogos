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
from cogtainer import naming
from cogtainer.aws import DEFAULT_ORG_PROFILE, DEFAULT_REGION, ORG_PROFILE_ENV, resolve_org_profile, set_org_profile
from cogtainer.deploy_config import CogtainerConfig

_PROFILE_HELP = f"AWS profile (default: ${ORG_PROFILE_ENV} or {DEFAULT_ORG_PROFILE})"


def _ecr_repo_from_ci_config() -> str:
    """Get the ECR repo name from CI config (first cogtainer entry)."""
    try:
        from cogtainer.ci_config import load_ci_config
        cfg = load_ci_config()
        if cfg.cogtainers:
            return next(iter(cfg.cogtainers.values())).ecr_repo
    except Exception:
        pass
    return naming.ecr_repo_name()


def _check_ecr_image_for_commit(
    session: boto3.Session, prefix: str = "executor", deploy_sha: str | None = None,
) -> str | None:
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

    ecr_repo = _ecr_repo_from_ci_config()
    ecr_client = session.client("ecr", region_name=DEFAULT_REGION)
    try:
        ecr_client.describe_images(
            repositoryName=ecr_repo,
            imageIds=[{"imageTag": expected_tag}],
        )
        click.echo(f"  ECR image for HEAD ({sha_short}): {click.style('found', fg='green')}")
        return expected_tag
    except Exception:
        deploy_msg = ""
        if deploy_sha:
            deploy_msg = f"\n  Deploying version {deploy_sha[:8]} from boot manifest."
        click.echo(
            click.style(
                f"  Warning: No ECR image found for current commit ({sha_short}).\n"
                f"  Expected tag: {expected_tag}\n"
                f"  Check CI: gh run list --repo Metta-AI/cogos --workflow docker-build-{prefix}.yml\n"
                f"  The deployed code may not match the running container.{deploy_msg}",
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
    Default (no subcommand): update all components (Lambda, RDS, dashboard, discord bridge).
    """
    pass


def _get_session(profile: str | None = None) -> boto3.Session:
    """Get a boto3 session for the cogtainer account."""
    from cogtainer.aws import get_aws_session

    set_org_profile(profile)
    session, _ = get_aws_session()
    return session


def _ensure_db_env(name: str, profile: str | None = None) -> None:
    """Ensure DB_CLUSTER_ARN, DB_SECRET_ARN, and DB_NAME are set from the shared cogtainer Aurora cluster."""
    safe_name = name.replace(".", "-")
    db_name = f"cogent_{safe_name.replace('-', '_')}"
    os.environ["DB_NAME"] = db_name

    if os.environ.get("DB_CLUSTER_ARN") and os.environ.get("DB_SECRET_ARN"):
        return

    from cogtainer.aws import get_aws_session

    set_org_profile(profile)
    session, _ = get_aws_session()

    # Look up DB connection info from DynamoDB cogent-status table
    ddb = session.resource("dynamodb", region_name=DEFAULT_REGION)
    try:
        item = ddb.Table("cogent-status").get_item(Key={"cogent_name": name}).get("Item", {})  # type: ignore[union-attr]
        db_info = item.get("database", {})
    except Exception:
        db_info = {}

    if db_info.get("cluster_arn"):
        os.environ["DB_CLUSTER_ARN"] = db_info["cluster_arn"]
        os.environ["DB_RESOURCE_ARN"] = db_info["cluster_arn"]
    if db_info.get("secret_arn"):
        os.environ["DB_SECRET_ARN"] = db_info["secret_arn"]

    creds = session.get_credentials().get_frozen_credentials()
    os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
    if creds.token:
        os.environ["AWS_SESSION_TOKEN"] = creds.token


def _create_repo(name: str, profile: str | None = None, client=None):  # noqa: ANN001, ANN201
    """Ensure DB env vars are set and return a repository instance."""
    _ensure_db_env(name, profile)
    from cogos.db.factory import create_repository

    if client is None:
        admin_session = _get_admin_session(profile)
        client = admin_session.client("rds-data", region_name=DEFAULT_REGION)

    return create_repository(
        resource_arn=os.environ.get("DB_CLUSTER_ARN") or os.environ.get("DB_RESOURCE_ARN"),
        secret_arn=os.environ.get("DB_SECRET_ARN"),
        database=os.environ.get("DB_NAME"),
        region=os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION),
        client=client,
    )


def _package_lambda_code() -> bytes:
    """Zip the src/ directory with pip-installed dependencies for Lambda deployment.

    The Lambda handler expects top-level packages (cogtainer/, memory/, etc.) without
    a src/ prefix, so we use src_dir as the base for archive paths.  Dependencies
    are installed into a temporary directory and bundled into the same zip.
    """
    import subprocess
    import tempfile

    src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)))
    _project_root = os.path.dirname(src_dir)

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
        "PyYAML",
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
        # Add source code (cogtainer/, memory/, channels/, etc.)
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
@click.option("--skip-health", is_flag=True, help="Skip waiting for ECS service stability")
@click.pass_context
def update_all(ctx: click.Context, profile: str | None, skip_health: bool):
    """Update all components: Lambda, DB migrations, dashboard, and discord bridge."""
    profile = resolve_org_profile(profile)
    t0 = time.monotonic()
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_rds, profile=profile, force=False)
    ctx.invoke(update_dashboard, skip_health=skip_health)
    ctx.invoke(update_discord, profile=profile, skip_health=skip_health)
    click.echo(f"\nTotal: {time.monotonic() - t0:.1f}s")


def _read_local_versions() -> dict[str, str] | None:
    """Read versions from local images/cogos/versions.defaults.json (updated by CI)."""
    try:
        import json as _json

        versions_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "images", "cogos", "versions.defaults.json",
        )
        with open(versions_path) as f:
            return _json.load(f)
    except Exception:
        return None


def _read_boot_versions(name: str) -> dict[str, str] | None:
    """Read versions: prefer local versions.defaults.json, fall back to DB."""
    local = _read_local_versions()
    if local:
        return local

    try:
        import json as _json

        from cogos.files.store import FileStore
        fs = FileStore(_create_repo(name))
        content = fs.get_content("mnt/boot/versions.json")
        if content:
            return _json.loads(content).get("components", {})
    except Exception:
        pass
    return None


def _update_boot_versions(name: str, updates: dict[str, str]) -> None:
    """Best-effort write-back of deployed versions to DB boot manifest."""
    try:
        import json as _json

        from cogos.files.store import FileStore

        fs = FileStore(_create_repo(name))
        content = fs.get_content("mnt/boot/versions.json")
        manifest = _json.loads(content) if content else {"components": {}}
        manifest.setdefault("components", {}).update(updates)
        fs.upsert("mnt/boot/versions.json", _json.dumps(manifest))
    except Exception:
        pass


@update.command("lambda")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--sha", default=None, help="Use pre-built lambda zip from CI (git SHA)")
@click.pass_context
def update_lambda(ctx: click.Context, profile: str | None, sha: str | None):
    """Update Lambda function code."""
    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    _ensure_db_env(name, profile)
    session = _get_session(profile)
    safe_name = name.replace(".", "-")

    cogtainer_name = (ctx.find_root().obj or {}).get("cogtainer_name", "")
    click.echo(f"Updating cogent-{name} Lambda functions...")

    if not sha:
        versions = _read_boot_versions(name)
        if versions and versions.get("lambda") and versions["lambda"] != "local":
            sha = versions["lambda"]
            click.echo(f"  Using lambda version from boot manifest: {sha[:8]}")

    _check_ecr_image_for_commit(session, "executor", deploy_sha=sha)

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
        except Exception as e:
            raise click.ClickException(
                f"CI artifact not found: s3://{_ci_artifacts_bucket()}/{s3_key}\n"
                f"Check CI: gh run list --repo Metta-AI/cogos --workflow docker-build-executor.yml"
            ) from e
        finally:
            os.unlink(tmp_path)
    else:
        zip_bytes = _package_lambda_code()
    pkg_time = time.monotonic() - t0
    click.echo(f"  Package: {len(zip_bytes) / 1024:.0f} KB ({pkg_time:.1f}s)")

    lambda_client = session.client("lambda", region_name=DEFAULT_REGION)

    if cogtainer_name:
        lambda_functions = [
            f"cogtainer-{cogtainer_name}-{safe_name}-event-router",
            f"cogtainer-{cogtainer_name}-{safe_name}-executor",
            f"cogtainer-{cogtainer_name}-{safe_name}-dispatcher",
        ]
    else:
        lambda_functions = [
            f"cogent-{safe_name}-event-router",
            f"cogent-{safe_name}-executor",
            f"cogent-{safe_name}-dispatcher",
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
        _create_repo(name).set_meta("content:deployed_at")
    except Exception:
        pass

    _update_boot_versions(name, {"lambda": sha or "local"})
    click.echo(f"  Lambda: {time.monotonic() - t0:.1f}s")


def _find_ecs_service(ecs_client, safe_name: str, service_type: str = "dashboard") -> str | None:
    """Find an ECS service for a cogent by type (dashboard or discord)."""
    cluster = naming.cluster_name()
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


def _update_ecs_image(ecs_client, session, service_arn: str, tag: str) -> tuple[str, str]:
    """Verify ECR tag exists, update task definition with new image.

    Returns (new_task_def_arn, old_task_def_arn).
    """
    from cogtainer.aws import ACCOUNT_ID

    ecr_repo = _ecr_repo_from_ci_config()
    repo_uri = f"{ACCOUNT_ID}.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/{ecr_repo}"
    new_image = f"{repo_uri}:{tag}"
    click.echo(f"  Image: {new_image}")

    # Verify the tag exists in ECR
    ecr_client = session.client("ecr", region_name=DEFAULT_REGION)
    try:
        ecr_client.describe_images(
            repositoryName=ecr_repo,
            imageIds=[{"imageTag": tag}],
        )
        click.echo(f"  ECR tag '{tag}': {click.style('found', fg='green')}")
    except Exception as e:
        # Determine the right workflow name from the tag prefix
        prefix = tag.split("-")[0] if "-" in tag else tag
        raise click.ClickException(
            f"ECR tag '{tag}' not found in cogent repo. "
            f"Check CI build status: gh run list --repo Metta-AI/cogos --workflow docker-build-{prefix}.yml"
        ) from e

    services = ecs_client.describe_services(cluster=naming.cluster_name(), services=[service_arn])["services"]
    if not services:
        raise click.ClickException(f"ECS service not found: {service_arn}")
    svc_desc = services[0]
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
    return new_td_arn, task_def_arn


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
    cluster = naming.cluster_name()

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)

    service_arn = _find_ecs_service(ecs_client, safe_name, "dashboard")
    if not service_arn:
        click.echo(f"  No dashboard ECS service found for cogent-{name} in {cluster}.")
        return

    click.echo(f"Forcing new ECS deployment for cogent-{name}...")
    click.echo(f"  Cluster: {cluster}")
    click.echo(f"  Service: {service_arn}")

    update_kwargs: dict = {
        "cluster": cluster,
        "service": service_arn,
        "forceNewDeployment": True,
    }

    old_td_arn = None
    if tag:
        new_td_arn, old_td_arn = _update_ecs_image(ecs_client, session, service_arn, tag)
        update_kwargs["taskDefinition"] = new_td_arn

    ecs_client.update_service(**update_kwargs)

    if old_td_arn:
        try:
            ecs_client.deregister_task_definition(taskDefinition=old_td_arn)
            click.echo(f"  Deregistered old task definition: {old_td_arn.split('/')[-1]}")
        except Exception:
            pass

    if not skip_health:
        click.echo("  Waiting for service to stabilize...")
        try:
            waiter = ecs_client.get_waiter("services_stable")
            waiter.wait(cluster=cluster, services=[service_arn])
            click.echo(f"  ECS deployment for cogent-{name} completed.")
        except Exception as e:
            click.echo(f"  Service did not stabilize: {e}", err=True)
            sys.exit(1)
    else:
        click.echo(f"  ECS deployment for cogent-{name} initiated.")


@update.command("discord")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.option("--tag", default=None, help="ECR image tag to deploy (e.g. discord-bridge-abc1234)")
@click.pass_context
def update_discord(ctx: click.Context, profile: str | None, skip_health: bool, tag: str | None):
    """Update the discord bridge ECS service.

    \b
    Deploys a new image to the discord bridge Fargate service.
    Uses the version from boot manifest by default, or specify --tag.
    """
    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    session = _get_session(profile)
    cluster = naming.cluster_name()

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)
    service_arn = _find_ecs_service(ecs_client, safe_name, "discord")
    if not service_arn:
        click.echo(f"  No discord bridge ECS service found for cogent-{name} in {cluster}. Skipping.")
        return

    if not tag:
        versions = _read_boot_versions(name)
        if versions and versions.get("discord_bridge") and versions["discord_bridge"] != "local":
            tag = f"discord-bridge-{versions['discord_bridge']}"
            click.echo(f"  Using discord_bridge version from boot manifest: {tag}")

    click.echo(f"Updating discord bridge for cogent-{name}...")
    click.echo(f"  Cluster: {cluster}")
    click.echo(f"  Service: {service_arn}")

    t0 = time.monotonic()
    update_kwargs: dict = {
        "cluster": cluster,
        "service": service_arn,
        "forceNewDeployment": True,
    }

    old_td_arn = None
    if tag:
        new_td_arn, old_td_arn = _update_ecs_image(ecs_client, session, service_arn, tag)
        update_kwargs["taskDefinition"] = new_td_arn

    ecs_client.update_service(**update_kwargs)

    if old_td_arn:
        try:
            ecs_client.deregister_task_definition(taskDefinition=old_td_arn)
            click.echo(f"  Deregistered old task definition: {old_td_arn.split('/')[-1]}")
        except Exception:
            pass

    if not skip_health:
        click.echo("  Waiting for service to stabilize...")
        try:
            waiter = ecs_client.get_waiter("services_stable")
            waiter.wait(cluster=cluster, services=[service_arn])
            click.echo(f"  Discord bridge: {click.style('deployed', fg='green')} ({time.monotonic() - t0:.1f}s)")
        except Exception as e:
            click.echo(f"  Service did not stabilize: {e}", err=True)
            click.echo("  The deployment is still in progress. Check ECS console.")
    else:
        click.echo(f"  Discord bridge deployment initiated. ({time.monotonic() - t0:.1f}s)")


@update.command("rds")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--force", is_flag=True, help="Force re-run migrations")
@click.pass_context
def update_rds(ctx: click.Context, profile: str | None, force: bool):
    """Run database schema migrations via Data API."""
    from cogos.db.migrations import apply_cogos_sql_migrations, apply_schema

    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    click.echo(f"Running migrations for cogent-{name} via Data API...")

    admin_session = _get_admin_session(profile)
    rds_client = admin_session.client("rds-data", region_name=DEFAULT_REGION)
    version = apply_schema(client=rds_client)

    repo = _create_repo(name, profile, client=rds_client)
    statements = apply_cogos_sql_migrations(repo)

    # Record schema migration timestamp
    try:
        repo.set_meta("schema:migrated_at", str(version))
    except Exception:
        pass

    click.echo(f"  Schema at version {version}.")
    click.echo(f"  CogOS SQL migrations applied ({statements} statements). ({time.monotonic() - t0:.1f}s)")


def _get_admin_session(profile: str | None = None):
    """Get a cogtainer session with full admin (OrganizationAccountAccessRole)."""
    from cogtainer.aws import ACCOUNT_ID, _assume_role

    resolved_profile = resolve_org_profile(profile)
    org_session = boto3.Session(profile_name=resolved_profile, region_name=DEFAULT_REGION)
    return _assume_role(org_session, ACCOUNT_ID, "OrganizationAccountAccessRole")



def _ci_artifacts_bucket() -> str:
    from cogtainer.ci_config import load_ci_config
    return load_ci_config().ci_artifacts_bucket


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
    s3_client.download_file(_ci_artifacts_bucket(), s3_key, dest_path)


def _is_dashboard_service_name(service_name: str, safe_name: str) -> bool:
    """Return True when the ECS service name belongs to the dashboard."""
    return safe_name in service_name and ("DashService" in service_name or "dashboard" in service_name)


def _find_dashboard_service(ecs_client, safe_name: str) -> str:
    """Find the dashboard ECS service ARN on the cogtainer cluster."""
    cluster = naming.cluster_name()
    services = ecs_client.list_services(cluster=cluster).get("serviceArns", [])
    dash_services = [s for s in services if _is_dashboard_service_name(s.rsplit("/", 1)[-1], safe_name)]
    if not dash_services:
        raise click.ClickException(f"No dashboard service found for {safe_name} on {cluster} cluster")
    return dash_services[0]


def _deploy_dashboard_image(ecs_client, service_arn: str, image_uri: str):
    """Update the ECS service's task def to use a new image and force deploy."""
    cluster = naming.cluster_name()
    services = ecs_client.describe_services(cluster=cluster, services=[service_arn])["services"]
    if not services:
        raise click.ClickException(f"Service not found: {service_arn}")

    task_def = ecs_client.describe_task_definition(
        taskDefinition=services[0]["taskDefinition"]
    )["taskDefinition"]

    # Update image in container definitions
    for c in task_def["containerDefinitions"]:
        if c.get("name") == "web":
            c["image"] = image_uri
            # Remove stale env vars from previous deploys
            c["environment"] = [
                e for e in c.get("environment", [])
                if e["name"] not in ("DASHBOARD_ASSETS_S3", "DASHBOARD_DOCKER_VERSION")
            ]

    # Register new task def revision
    reg_fields = [
        "family", "containerDefinitions", "taskRoleArn", "executionRoleArn",
        "networkMode", "requiresCompatibilities", "cpu", "memory",
    ]
    reg_kwargs = {k: task_def[k] for k in reg_fields if k in task_def}
    new_td = ecs_client.register_task_definition(**reg_kwargs)
    new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
    click.echo(f"  Task def: {new_td_arn.split('/')[-1]}")

    # Force new deployment
    ecs_client.update_service(
        cluster=cluster,
        service=service_arn,
        taskDefinition=new_td_arn,
        forceNewDeployment=True,
    )
    click.echo(f"  Image: {image_uri}")


def _wait_for_service_stable(ecs_client, safe_name: str, timeout: int = 120):
    """Wait for ECS service to stabilize after deployment."""
    cluster = naming.cluster_name()
    service_arn = _find_dashboard_service(ecs_client, safe_name)
    click.echo("  Waiting for service to stabilize...")
    t0 = time.monotonic()
    waiter = ecs_client.get_waiter("services_stable")
    try:
        waiter.wait(
            cluster=cluster,
            services=[service_arn],
            WaiterConfig={"Delay": 6, "MaxAttempts": timeout // 6},
        )
        click.echo(f"  Service: {click.style('stable', fg='green')} ({time.monotonic() - t0:.1f}s)")
    except Exception as e:
        click.echo(click.style(f"  Service did not stabilize within {timeout}s: {e}", fg="yellow"))


@update.command("dashboard")
@click.option("--sha", default=None, help="Git SHA to deploy (default: latest from versions.defaults.json)")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_dashboard(ctx: click.Context, sha: str | None, skip_health: bool):
    """Deploy a dashboard version by updating the ECS image tag.

    \b
    Resolves the SHA, updates the ECS task definition to point to
    cogent-dashboard:{sha} in shared ECR, and forces a new deployment.
    ~60-90s for the new task to be healthy.
    """
    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    session = _get_admin_session()

    # Resolve SHA: explicit > versions.defaults.json > "latest"
    if not sha:
        versions = _read_boot_versions(name)
        sha = (versions or {}).get("dashboard", "latest")
    click.echo(f"Deploying dashboard {sha} for cogent-{name}...")

    # Update ECS task def image tag and force new deployment
    from cogtainer.aws import ACCOUNT_ID
    image_uri = f"{ACCOUNT_ID}.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/cogent-dashboard:{sha}"

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)
    service_arn = _find_dashboard_service(ecs_client, safe_name)
    _deploy_dashboard_image(ecs_client, service_arn, image_uri)

    # Purge CDN cache
    click.echo("  Purging CDN cache...")
    try:
        from cogtainer.cloudflare import purge_cache
        from cogtainer.secret_store import SecretStore
        store = SecretStore(session=session)
        purge_cache(store)
        click.echo(f"  Cache: {click.style('purged', fg='green')}")
    except Exception as e:
        click.echo(f"  Cache purge failed (non-fatal): {e}")

    if not skip_health:
        _wait_for_service_stable(ecs_client, safe_name)

    _update_boot_versions(name, {"dashboard": sha or "local"})
    click.echo(f"  Dashboard: {click.style('deployed', fg='green')} ({time.monotonic() - t0:.1f}s)")


@update.command("stack")
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.pass_context
def update_stack(ctx: click.Context, profile: str | None):
    """Full CDK stack update via the cogtainer CDK app."""
    import subprocess

    from cogtainer.aws import get_aws_session, resolve_org_profile, set_profile

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    cogtainer_name = (ctx.find_root().obj or {}).get("cogtainer_name", "")
    profile = resolve_org_profile(profile)

    # Look up certificate ARN from cogtainer account
    set_profile(profile)
    session, _ = get_aws_session()
    cf = session.client("cloudformation", region_name=DEFAULT_REGION)
    acm = session.client("acm", region_name=DEFAULT_REGION)
    cert_arn = ""
    domain = f"{safe_name}.{CogtainerConfig().domain}"
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
        click.echo("Warning: Could not resolve cogtainer ECR repo. Using default image.")

    # Resolve shared infra from cogtainer stack outputs (source of truth)
    cogtainer_stack = cf.describe_stacks(StackName=naming.cogtainer_stack_name())["Stacks"][0]
    cogtainer_outputs = {o["OutputKey"]: o["OutputValue"] for o in cogtainer_stack.get("Outputs", [])}
    shared_db_cluster_arn = cogtainer_outputs.get("SharedDbClusterArn", "")
    shared_db_secret_arn = cogtainer_outputs.get("SharedDbSecretArn", "")
    shared_alb_listener_arn = cogtainer_outputs.get("SharedHttpsListenerArn", "")
    shared_alb_sg_id = cogtainer_outputs.get("SharedAlbSecurityGroupId", "")

    click.echo(f"Updating CDK stack for cogent-{name}...")
    stack = f"cogtainer-{cogtainer_name}-{safe_name}" if cogtainer_name else naming.stack_name(name)
    cmd = [
        "npx",
        "cdk",
        "deploy",
        stack,
        "-c",
        f"cogtainer_name={cogtainer_name}",
        "-c",
        f"cogent_name={name}",
        "-c",
        f"certificate_arn={cert_arn}",
        "-c",
        f"ecr_repo_uri={ecr_repo_uri}",
        "-c",
        f"shared_db_cluster_arn={shared_db_cluster_arn}",
        "-c",
        f"shared_db_secret_arn={shared_db_secret_arn}",
        "-c",
        f"shared_alb_listener_arn={shared_alb_listener_arn}",
        "-c",
        f"shared_alb_security_group_id={shared_alb_sg_id}",
        "--app",
        "python -m cogtainer.cdk.app",
        "--require-approval",
        "never",
    ]
    env = {**os.environ, "AWS_PROFILE": profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")

    # Record stack update timestamp
    try:
        _create_repo(name).set_meta("stack:updated_at")
    except Exception:
        pass

    click.echo(f"Stack update for cogent-{name} completed.")
