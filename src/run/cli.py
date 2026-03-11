"""cogent run — interact with running ECS tasks."""

from __future__ import annotations

import json
import os
import time

import click
from rich.console import Console
from rich.table import Table

from cli import get_cogent_name


@click.group()
def run():
    """Interact with running ECS tasks."""
    pass


def _list_running_tasks(ecs_client, cluster: str, family: str = "") -> list[dict]:
    """List running ECS tasks with their details."""
    kwargs = {"cluster": cluster, "desiredStatus": "RUNNING"}
    if family:
        kwargs["family"] = family
    task_arns = ecs_client.list_tasks(**kwargs).get("taskArns", [])
    if not task_arns:
        return []
    resp = ecs_client.describe_tasks(cluster=cluster, tasks=task_arns)
    return resp.get("tasks", [])


def _extract_env(task: dict, var_name: str) -> str:
    """Extract an environment variable from a task's container overrides."""
    for override in task.get("overrides", {}).get("containerOverrides", []):
        for env in override.get("environment", []):
            if env["name"] == var_name:
                return env["value"]
    return ""


def _task_id_from_arn(arn: str) -> str:
    """Extract task ID from full ARN."""
    return arn.rsplit("/", 1)[-1]


def _get_program_name(task: dict) -> str:
    """Extract program name from task's EXECUTOR_PAYLOAD env var."""
    payload_json = _extract_env(task, "EXECUTOR_PAYLOAD")
    if not payload_json:
        return ""
    try:
        payload = json.loads(payload_json)
        return payload.get("trigger", {}).get("program_name", "")
    except (json.JSONDecodeError, KeyError):
        return ""


@run.command("list")
@click.pass_context
def list_cmd(ctx: click.Context):
    """List running ECS tasks."""
    name = get_cogent_name(ctx)
    cfg = _get_ecs_config(name)
    cluster = cfg["cluster"]
    ecs_client = cfg["ecs_client"]
    family = cfg["family"]

    tasks = _list_running_tasks(ecs_client, cluster, family)
    if not tasks:
        click.echo("No running tasks.")
        return

    console = Console()
    cluster_name = cluster.rsplit("/", 1)[-1] if "/" in cluster else cluster
    table = Table(title=f"Running tasks — {cluster_name}")
    table.add_column("Task ID", style="cyan")
    table.add_column("Program")
    table.add_column("Started")
    table.add_column("Status")

    for task in tasks:
        task_id = _task_id_from_arn(task["taskArn"])
        program = _get_program_name(task)
        started = task.get("startedAt", "")
        if started and hasattr(started, "strftime"):
            started = started.strftime("%H:%M:%S")
        else:
            started = str(started)
        status = task.get("lastStatus", "")
        table.add_row(task_id, program, started, status)

    console.print(table)


def _get_ecs_config(name: str) -> dict:
    """Get ECS config from the brain's orchestrator Lambda environment."""
    from polis.aws import get_polis_session, set_org_profile

    set_org_profile()
    session, _ = get_polis_session()
    lambda_client = session.client("lambda")
    safe_name = name.replace(".", "-")
    resp = lambda_client.get_function(FunctionName=f"cogent-{safe_name}-orchestrator")
    env = resp["Configuration"]["Environment"]["Variables"]
    task_def_arn = env["ECS_TASK_DEFINITION"]
    # Extract family from ARN: .../cogent-dr-alpha-executor:9 → cogent-dr-alpha-executor
    family = task_def_arn.rsplit("/", 1)[-1].split(":")[0]
    return {
        "cluster": env["ECS_CLUSTER_ARN"],
        "task_definition": task_def_arn,
        "family": family,
        "subnets": [s.strip() for s in env["ECS_SUBNETS"].split(",")],
        "security_group": env["ECS_SECURITY_GROUP"],
        "session": session,
        "ecs_client": session.client("ecs"),
    }


def _launch_shell_task(cfg: dict) -> None:
    """Launch a bare ECS task (no program) for interactive shell access."""
    click.echo("Launching shell task...")
    cfg["ecs_client"].run_task(
        cluster=cfg["cluster"],
        taskDefinition=cfg["task_definition"],
        launchType="FARGATE",
        enableExecuteCommand=True,
        overrides={
            "containerOverrides": [{
                "name": "Executor",
                "environment": [
                    {"name": "SHELL_CMD", "value": "claude"},
                ],
            }],
        },
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": cfg["subnets"],
                "securityGroups": [cfg["security_group"]],
                "assignPublicIp": "ENABLED",
            }
        },
    )
    click.echo("Shell task launched.")


def _wait_for_task(ecs_client, cluster: str, family: str = "", timeout: int = 180) -> dict | None:
    """Poll for a new task with SSM agent ready, showing inline status."""
    last_status = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check all tasks (RUNNING and not-yet-running)
        all_arns = []
        for desired in ("RUNNING", "STOPPED"):
            kwargs = {"cluster": cluster, "desiredStatus": desired}
            if family:
                kwargs["family"] = family
            arns = ecs_client.list_tasks(**kwargs).get("taskArns", [])
            all_arns.extend(arns)

        if all_arns:
            desc = ecs_client.describe_tasks(cluster=cluster, tasks=all_arns[-10:])
            for task in desc.get("tasks", []):
                status = task.get("lastStatus", "UNKNOWN")
                # SSM agent ready — good to connect
                for container in task.get("containers", []):
                    for agent in container.get("managedAgents", []):
                        if agent.get("name") == "ExecuteCommandAgent" and agent.get("lastStatus") == "RUNNING":
                            click.echo("\r\033[K" + "Ready.", nl=True)
                            return task
                # Show progress inline
                if status != last_status:
                    label = {
                        "PROVISIONING": "Provisioning task...",
                        "PENDING": "Waiting for container...",
                        "ACTIVATING": "Starting container...",
                        "RUNNING": "Waiting for SSM agent...",
                        "DEACTIVATING": "Task stopping...",
                        "STOPPED": "Task stopped unexpectedly.",
                    }.get(status, f"Status: {status}")
                    click.echo("\r\033[K" + label, nl=False)
                    last_status = status
        elif not last_status:
            click.echo("\r\033[K" + "Waiting for task to be scheduled...", nl=False)
            last_status = "NONE"

        time.sleep(3)
    click.echo()
    return None


@run.command("shell")
@click.argument("run_id", required=False)
@click.option("--new", "launch_new", is_flag=True, help="Launch a new shell task")
@click.pass_context
def shell_cmd(ctx: click.Context, run_id: str | None, launch_new: bool):
    """Attach to a running ECS task's tmux session.

    If RUN_ID is provided, connect to that specific task.
    Otherwise, list running tasks and prompt for selection.
    Use --new to launch a fresh shell task.
    """
    name = get_cogent_name(ctx)
    cfg = _get_ecs_config(name)
    cluster = cfg["cluster"]
    ecs_client = cfg["ecs_client"]
    family = cfg["family"]

    if launch_new:
        _launch_shell_task(cfg)
        target = _wait_for_task(ecs_client, cluster, family)
        if not target:
            raise click.ClickException("Timed out waiting for task to start")
        _connect(cluster, target)
        return

    tasks = _list_running_tasks(ecs_client, cluster, family)

    if not tasks:
        if click.confirm("No running tasks. Launch a new shell?", default=True):
            _launch_shell_task(cfg)
            target = _wait_for_task(ecs_client, cluster, family)
            if not target:
                raise click.ClickException("Timed out waiting for task to start")
            _connect(cluster, target)
        return

    if run_id:
        target = None
        for task in tasks:
            task_id = _task_id_from_arn(task["taskArn"])
            if task_id == run_id or task_id.startswith(run_id):
                target = task
                break
        if not target:
            click.echo(f"No running task found matching: {run_id}")
            return
    elif len(tasks) == 1:
        target = tasks[0]
    else:
        click.echo("Running tasks:")
        for i, task in enumerate(tasks):
            task_id = _task_id_from_arn(task["taskArn"])
            program = _get_program_name(task) or "shell"
            started = task.get("startedAt", "")
            if started and hasattr(started, "strftime"):
                started = started.strftime("%H:%M")
            else:
                started = ""
            click.echo(f"  [{i}] {program}  ({task_id[:8]}, {started})" if started else f"  [{i}] {program}  ({task_id[:8]})")
        click.echo(f"  [n] Launch new shell")

        choice = click.prompt("Select task", default="0")
        if choice.lower() == "n":
            _launch_shell_task(cfg)
            target = _wait_for_task(ecs_client, cluster, family)
            if not target:
                raise click.ClickException("Timed out waiting for task to start")
            _connect(cluster, target)
            return

        idx = int(choice)
        if idx < 0 or idx >= len(tasks):
            click.echo("Invalid selection.")
            return
        target = tasks[idx]

    _connect(cluster, target)


def _connect(cluster: str, target: dict) -> None:
    """Connect to a task's tmux session via ECS Exec."""
    import subprocess

    from polis.aws import get_polis_session, set_org_profile

    set_org_profile()
    session, _ = get_polis_session()
    creds = session.get_credentials().get_frozen_credentials()

    task_arn = target["taskArn"]
    task_id = _task_id_from_arn(task_arn)
    click.echo(f"Connecting to {task_id[:12]}...")

    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = creds.access_key
    env["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
    if creds.token:
        env["AWS_SESSION_TOKEN"] = creds.token
    env["AWS_DEFAULT_REGION"] = "us-east-1"
    env.pop("AWS_PROFILE", None)

    cmd = [
        "aws", "ecs", "execute-command",
        "--cluster", cluster,
        "--task", task_arn,
        "--container", "Executor",
        "--interactive",
        "--command", "/bin/bash -c 'tmux attach -t claude 2>/dev/null || bash'",
    ]
    result = subprocess.run(cmd, env=env)
    raise SystemExit(result.returncode)
