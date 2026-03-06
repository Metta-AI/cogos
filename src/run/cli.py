"""cogent run — interact with running ECS tasks."""

from __future__ import annotations

import json
import os
import subprocess
import time

import boto3
import click
from rich.console import Console
from rich.table import Table

from cli import get_cogent_name


@click.group()
def run():
    """Interact with running ECS tasks."""
    pass


def _get_cluster_name(cogent_name: str) -> str:
    return f"cogent-{cogent_name.replace('.', '-')}"


def _list_running_tasks(ecs_client, cluster: str) -> list[dict]:
    """List running ECS tasks with their details."""
    task_arns = ecs_client.list_tasks(
        cluster=cluster, desiredStatus="RUNNING"
    ).get("taskArns", [])
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
    cluster = _get_cluster_name(name)
    ecs_client = boto3.client("ecs")

    tasks = _list_running_tasks(ecs_client, cluster)
    if not tasks:
        click.echo("No running tasks.")
        return

    console = Console()
    table = Table(title=f"Running tasks — {cluster}")
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


def _launch_shell_task(name: str) -> None:
    """Launch a new shell task via mind task create --run."""
    safe_name = name.replace(".", "-")
    cmd = [
        "cogent", name,
        "mind", "task", "create", f"shell-{safe_name}",
        "--program", "vsm/s1/do-content",
        "--content", "Interactive shell session",
        "--runner", "ecs",
        "--run",
    ]
    click.echo("Creating task...")
    subprocess.run(cmd, check=True)


def _wait_for_task(ecs_client, cluster: str, timeout: int = 120) -> dict | None:
    """Poll for a new RUNNING task with SSM agent ready."""
    click.echo("Waiting for ECS task to start...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        tasks = _list_running_tasks(ecs_client, cluster)
        for task in tasks:
            # Check if SSM managed agent is running (needed for ECS Exec)
            for container in task.get("containers", []):
                for agent in container.get("managedAgents", []):
                    if agent.get("name") == "ExecuteCommandAgent" and agent.get("lastStatus") == "RUNNING":
                        return task
        time.sleep(5)
        click.echo("  ...")
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
    cluster = _get_cluster_name(name)
    ecs_client = boto3.client("ecs")

    if launch_new:
        _launch_shell_task(name)
        target = _wait_for_task(ecs_client, cluster)
        if not target:
            raise click.ClickException("Timed out waiting for task to start")
        _connect(cluster, target)
        return

    tasks = _list_running_tasks(ecs_client, cluster)

    if not tasks:
        if click.confirm("No running tasks. Launch a new shell?", default=True):
            _launch_shell_task(name)
            target = _wait_for_task(ecs_client, cluster)
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
            program = _get_program_name(task)
            click.echo(f"  [{i}] {task_id[:12]}  {program}")
        click.echo(f"  [n] Launch new shell")

        choice = click.prompt("Select task", default="0")
        if choice.lower() == "n":
            _launch_shell_task(name)
            target = _wait_for_task(ecs_client, cluster)
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
    task_arn = target["taskArn"]
    task_id = _task_id_from_arn(task_arn)
    click.echo(f"Connecting to {task_id[:12]}...")

    cmd = [
        "aws", "ecs", "execute-command",
        "--cluster", cluster,
        "--task", task_arn,
        "--container", "Executor",
        "--interactive",
        "--command", "tmux attach -t claude",
    ]
    os.execvp("aws", cmd)
