from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click
from polis.aws import DEFAULT_ORG_PROFILE, ORG_PROFILE_ENV, resolve_org_profile

_COGENT_DIR = Path.home() / ".cogents"
_REPO_ROOT = Path(__file__).parent.parent.parent
_FRONTEND_DIR = _REPO_ROOT / "dashboard" / "frontend"
_PROFILE_HELP = f"AWS profile for DB lookup (default: ${ORG_PROFILE_ENV} or {DEFAULT_ORG_PROFILE})"
_REQUIRED_DB_ENV = ("DB_RESOURCE_ARN", "DB_SECRET_ARN", "DB_NAME")


def _checkout_ports() -> tuple[int, int]:
    """Read BE/FE ports from repo root .env file."""
    env_file = _REPO_ROOT / ".env"
    be, fe = 8100, 5200
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split("#")[0].strip()
            if k == "DASHBOARD_BE_PORT":
                be = int(v)
            elif k == "DASHBOARD_FE_PORT":
                fe = int(v)
    return be, fe


def _key_file(name: str) -> Path:
    safe = name.replace(".", "-")
    d = _COGENT_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d / "dashboard-key"


def _frontend_next_bin() -> Path:
    bin_name = "next.cmd" if os.name == "nt" else "next"
    return _FRONTEND_DIR / "node_modules" / ".bin" / bin_name


def _ensure_frontend_ready() -> None:
    """Fail fast if the local frontend dependencies are missing."""
    if not _FRONTEND_DIR.exists():
        return

    next_bin = _frontend_next_bin()
    if next_bin.exists():
        return

    install_cmd = "cd dashboard/frontend && npm ci"
    if not (_FRONTEND_DIR / "package-lock.json").exists():
        install_cmd = "cd dashboard/frontend && npm install"

    raise click.ClickException(
        "Dashboard frontend dependencies are not installed.\n"
        f"Expected local Next.js binary at `{next_bin}`.\n"
        f"Run `{install_cmd}` and retry."
    )


def _normalize_db_env(env: dict[str, str]) -> dict[str, str]:
    """Mirror the cluster/resource ARN names used across the repo."""
    if env.get("DB_CLUSTER_ARN") and not env.get("DB_RESOURCE_ARN"):
        env["DB_RESOURCE_ARN"] = env["DB_CLUSTER_ARN"]
    if env.get("DB_RESOURCE_ARN") and not env.get("DB_CLUSTER_ARN"):
        env["DB_CLUSTER_ARN"] = env["DB_RESOURCE_ARN"]
    return env


def _missing_db_env(env: dict[str, str]) -> list[str]:
    return [name for name in _REQUIRED_DB_ENV if not env.get(name)]


@click.group()
def dashboard():
    """Dashboard commands."""
    pass


def _ensure_db_env(
    name: str,
    env: dict[str, str],
    *,
    assume_polis: bool = False,
    profile: str | None = None,
) -> dict[str, str]:
    """Auto-discover DB ARNs from CloudFormation and add to env dict."""
    env = _normalize_db_env(env)
    if not assume_polis and env.get("DB_RESOURCE_ARN") and env.get("DB_SECRET_ARN"):
        env.setdefault("DB_NAME", "cogent")
        return env

    safe_name = name.replace(".", "-")
    stack_name = f"cogent-{safe_name}-brain"
    resolved_profile = resolve_org_profile(profile) if assume_polis else profile
    try:
        if assume_polis:
            from polis.aws import get_polis_session, set_org_profile

            set_org_profile(profile)
            session, _ = get_polis_session()
            cf = session.client("cloudformation", region_name="us-east-1")
        else:
            import boto3

            session = boto3.Session(profile_name=profile, region_name="us-east-1") if profile else boto3.Session()
            cf = session.client("cloudformation", region_name="us-east-1")
        resp = cf.describe_stacks(StackName=stack_name)
        outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
        if "ClusterArn" in outputs:
            env.setdefault("DB_RESOURCE_ARN", outputs["ClusterArn"])
            env.setdefault("DB_CLUSTER_ARN", outputs["ClusterArn"])
        if "SecretArn" in outputs:
            env.setdefault("DB_SECRET_ARN", outputs["SecretArn"])
        else:
            resources = cf.list_stack_resources(StackName=stack_name)
            for r in resources.get("StackResourceSummaries", []):
                if "Secret" in r["LogicalResourceId"] and "Attachment" not in r["LogicalResourceId"]:
                    if r["PhysicalResourceId"].startswith("arn:aws:secretsmanager:"):
                        env.setdefault("DB_SECRET_ARN", r["PhysicalResourceId"])
                        break
        env.setdefault("DB_NAME", "cogent")
        if assume_polis and session is not None:
            creds = session.get_credentials().get_frozen_credentials()
            env["AWS_ACCESS_KEY_ID"] = creds.access_key
            env["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
            if creds.token:
                env["AWS_SESSION_TOKEN"] = creds.token
            env.setdefault("AWS_DEFAULT_REGION", "us-east-1")
            env.setdefault("AWS_REGION", "us-east-1")
    except Exception as e:
        if assume_polis:
            raise click.ClickException(
                "Could not resolve live DB credentials for `--db prod`.\n"
                f"Cogent: {name}\n"
                f"Stack: {stack_name}\n"
                f"AWS profile: {resolved_profile}\n"
                f"Original error: {e}\n"
                f"Run `aws sso login --profile {resolved_profile}` or set `{ORG_PROFILE_ENV}` "
                "to a profile that can assume into polis."
            ) from e
        click.echo(f"Warning: could not auto-discover DB credentials: {e}")
    env.setdefault("DB_NAME", "cogent")
    return _normalize_db_env(env)


@dashboard.command()
@click.option("--port", default=None, type=int, help="Backend port (default: derived from checkout path)")
@click.option("--frontend-port", default=None, type=int, help="Frontend port (default: derived from checkout path)")
@click.option("--no-browser", is_flag=True, help="Don't open browser")
@click.option(
    "--db",
    "db_mode",
    type=click.Choice(["auto", "local", "prod"]),
    default="auto",
    show_default=True,
    help="DB source: ambient AWS/env (`auto`), local JSON repo (`local`), or polis-assumed live DB (`prod`).",
)
@click.option("--profile", default=None, help=_PROFILE_HELP)
@click.option("--local", is_flag=True, help="Use local DB (USE_LOCAL_DB=1)")
@click.pass_context
def serve(
    ctx: click.Context,
    port: int | None,
    frontend_port: int | None,
    no_browser: bool,
    db_mode: str,
    profile: str | None,
    local: bool,
):
    """Start the dashboard dev server."""
    from cli import get_cogent_name

    default_be, default_fe = _checkout_ports()
    port = port or default_be
    frontend_port = frontend_port or default_fe

    if local:
        if db_mode != "auto":
            raise click.UsageError("Use either --local or --db, not both.")
        db_mode = "local"

    name = get_cogent_name(ctx)
    env = {
        **os.environ,
        "DASHBOARD_COGENT_NAME": name,
        "DASHBOARD_PORT": str(port),
        "DASHBOARD_BE_PORT": str(port),
        "DASHBOARD_FE_PORT": str(frontend_port),
    }

    if db_mode == "local":
        env["USE_LOCAL_DB"] = "1"
    else:
        env = _ensure_db_env(name, env, assume_polis=(db_mode == "prod"), profile=profile)
        missing = _missing_db_env(env)
        if missing:
            if db_mode == "prod":
                resolved_profile = resolve_org_profile(profile)
                raise click.ClickException(
                    "Dashboard requires live DB credentials but `--db prod` did not resolve them.\n"
                    f"Missing: {', '.join(missing)}\n"
                    f"AWS profile: {resolved_profile}\n"
                    f"Run `aws sso login --profile {resolved_profile}` or set `{ORG_PROFILE_ENV}`."
                )
            raise click.ClickException(
                "Dashboard requires DB credentials for live data.\n"
                f"Missing: {', '.join(missing)}\n"
                "Export `DB_RESOURCE_ARN`, `DB_SECRET_ARN`, and `DB_NAME`, or use `--db local`."
            )

    _ensure_frontend_ready()

    # Start FastAPI backend
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", str(port)],
        env=env,
    )

    # Start Next.js frontend (if directory exists)
    frontend = None
    if _FRONTEND_DIR.exists():
        frontend = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(_FRONTEND_DIR),
            env=env,
        )
        time.sleep(1)
        if frontend.poll() is not None:
            backend.terminate()
            backend.wait(timeout=5)
            raise click.ClickException(
                "Dashboard frontend exited during startup. See the frontend error output above."
            )

    if not no_browser:
        url = f"http://localhost:{frontend_port}" if frontend else f"http://localhost:{port}"
        webbrowser.open(url)

    click.echo(f"Dashboard running: backend={port}, frontend={frontend_port}")
    click.echo("Press Ctrl+C to stop")

    def shutdown(sig, frame):
        backend.terminate()
        if frontend:
            frontend.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    backend.wait()


@dashboard.command()
@click.option("--docker", is_flag=True, help="Force rebuild Docker image")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def deploy(ctx: click.Context, docker: bool, skip_health: bool):
    """Deploy the dashboard (build frontend, push to S3/ECR, restart ECS)."""
    from brain.update_cli import update_dashboard

    ctx.invoke(update_dashboard, docker=docker, skip_health=skip_health)


@dashboard.command("create-pat")
@click.option("--force", is_flag=True, help="Overwrite existing PAT")
@click.pass_context
def create_pat(ctx: click.Context, force: bool):
    """Generate a Personal Access Token for API access (bypasses OAuth).

    The PAT is stored in polis secrets and used as an ALB bypass rule.
    After creating, run 'brain update stack' to apply the ALB rule.
    """
    from cli import get_cogent_name
    from polis.aws import get_polis_session, set_org_profile

    name = get_cogent_name(ctx)
    set_org_profile()
    session, _ = get_polis_session()

    from polis.secrets.store import SecretStore
    store = SecretStore(session=session)
    api_key_path = f"cogent/{name}/dashboard-api-key"

    # Check for existing
    existing = None
    try:
        existing = store.get(api_key_path, use_cache=False)
    except Exception:
        pass

    if existing and not force:
        click.echo(f"PAT already exists for {name}.")
        click.echo(f"Key: {existing['api_key']}")
        click.echo("Use --force to regenerate.")
        return

    key = secrets.token_urlsafe(48)
    store.put(api_key_path, {"api_key": key, "cogent": name})

    # Save locally too
    kf = _key_file(name)
    kf.write_text(key)

    click.echo(f"PAT created for {name}")
    click.echo(f"Key: {key}")
    click.echo(f"Saved locally to: {kf}")
    click.echo()
    click.echo("To activate the PAT as an ALB bypass rule, run:")
    click.echo(f"  cogent {name} brain update stack")
    click.echo()
    click.echo("Usage:")
    click.echo(f"  curl -H 'X-Api-Key: {key}' https://{name.replace('.', '-')}.softmax-cogents.com/api/...")


@dashboard.command("show-pat")
@click.pass_context
def show_pat(ctx: click.Context):
    """Show the dashboard PAT (from polis secrets)."""
    from cli import get_cogent_name
    from polis.aws import get_polis_session, set_org_profile

    name = get_cogent_name(ctx)
    set_org_profile()
    session, _ = get_polis_session()

    from polis.secrets.store import SecretStore
    store = SecretStore(session=session)
    try:
        secret = store.get(f"cogent/{name}/dashboard-api-key", use_cache=False)
        click.echo(f"PAT: {secret['api_key']}")
    except Exception:
        click.echo(f"No PAT found for {name}. Run: cogent {name} dashboard create-pat")


@dashboard.command()
@click.pass_context
def login(ctx: click.Context):
    """Generate and store an API key locally."""
    from cli import get_cogent_name

    name = get_cogent_name(ctx)
    key = secrets.token_urlsafe(32)
    kf = _key_file(name)
    kf.write_text(key)
    click.echo(f"API key saved to {kf}")
    click.echo(f"Key: {key}")


@dashboard.command()
@click.pass_context
def logout(ctx: click.Context):
    """Remove local API key."""
    from cli import get_cogent_name

    name = get_cogent_name(ctx)
    kf = _key_file(name)
    if kf.exists():
        kf.unlink()
        click.echo("API key removed")
    else:
        click.echo("No key found")


@dashboard.command()
@click.pass_context
def keys(ctx: click.Context):
    """Show local API key."""
    from cli import get_cogent_name

    name = get_cogent_name(ctx)
    kf = _key_file(name)
    if kf.exists():
        click.echo(f"Key: {kf.read_text().strip()}")
    else:
        click.echo("No key found. Run: cogent <name> dashboard login")
