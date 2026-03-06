from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import webbrowser
from pathlib import Path

import click

_COGENT_DIR = Path.home() / ".cogents"
_FRONTEND_DIR = Path(__file__).parent.parent.parent / "dashboard" / "frontend"


def _key_file(name: str) -> Path:
    safe = name.replace(".", "-")
    d = _COGENT_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d / "dashboard-key"


@click.group()
def dashboard():
    """Dashboard commands."""
    pass


def _ensure_db_env(name: str, env: dict) -> dict:
    """Auto-discover DB ARNs from CloudFormation and add to env dict."""
    if env.get("DB_RESOURCE_ARN") and env.get("DB_SECRET_ARN"):
        return env

    import boto3

    safe_name = name.replace(".", "-")
    stack_name = f"cogent-{safe_name}-brain"
    try:
        cf = boto3.client("cloudformation", region_name="us-east-1")
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
    except Exception as e:
        click.echo(f"Warning: could not auto-discover DB credentials: {e}")
    return env


@dashboard.command()
@click.option("--port", default=8100, help="Backend port")
@click.option("--frontend-port", default=5174, help="Frontend port")
@click.option("--no-browser", is_flag=True, help="Don't open browser")
@click.pass_context
def serve(ctx: click.Context, port: int, frontend_port: int, no_browser: bool):
    """Start the dashboard dev server."""
    from cli import get_cogent_name

    name = get_cogent_name(ctx)
    env = {
        **os.environ,
        "DASHBOARD_COGENT_NAME": name,
        "DASHBOARD_PORT": str(port),
    }
    env = _ensure_db_env(name, env)

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
            env={**env, "PORT": str(frontend_port)},
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
